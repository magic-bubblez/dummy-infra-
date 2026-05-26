import argparse
import json
import sys
from datetime import datetime, timezone

import boto3

from constants import EBS_GP3_PER_GB_MONTH, EIP_PER_HOUR, EC2_T3_MICRO_PER_HOUR, HOURS_PER_MONTH

ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
ACCOUNT_ID = "000000000000"
REQUIRED_TAGS = {"Project", "Environment", "Owner"}
STOPPED_DAYS_THRESHOLD = 14


def make_client(service: str):
    return boto3.client(
        service,
        region_name=REGION,
        endpoint_url=ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NimbusKart Cost Janitor — detect orphaned AWS resources")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Report orphans without deleting (default)")
    parser.add_argument("--delete", action="store_true", default=False, help="Delete orphans, skipping Protected=true resources")
    return parser.parse_args()


def tags_as_dict(tag_list: list) -> dict:
    """Convert AWS tag list [{"Key": k, "Value": v}] to a plain dict {k: v}."""
    if not tag_list:
        return {}
    return {t["Key"]: t["Value"] for t in tag_list}


def is_protected(tags: dict) -> bool:
    return tags.get("Protected", "").lower() == "true"


def missing_required_tags(tags: dict) -> list[str]:
    return [t for t in REQUIRED_TAGS if t not in tags]


def age_days(create_time: datetime) -> int:
    return (datetime.now(timezone.utc) - create_time).days


# ── detectors ────────────────────────────────────────────────────────────────

def find_unattached_ebs(ec2) -> list[dict]:
    response = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
    findings = []
    for vol in response["Volumes"]:
        tags = tags_as_dict(vol.get("Tags", []))
        size_gb = vol["Size"]
        findings.append({
            "resource_id": vol["VolumeId"],
            "resource_type": "ebs_volume",
            "reason": "unattached",
            "age_days": age_days(vol["CreateTime"]),
            "estimated_monthly_cost_usd": round(size_gb * EBS_GP3_PER_GB_MONTH, 2),
            "tags": {k: tags.get(k) for k in REQUIRED_TAGS},
            "suggested_action": "delete",
            "safe_to_auto_delete": False,
        })
    return findings


def find_long_stopped_instances(ec2) -> list[dict]:
    response = ec2.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}])
    findings = []
    for reservation in response["Reservations"]:
        for inst in reservation["Instances"]:
            tags = tags_as_dict(inst.get("Tags", []))
            stopped_since = inst.get("StateTransitionReason", "")
            # StateTransitionReason format: "User initiated (2026-01-01 00:00:00 GMT)"
            days = 0
            try:
                date_str = stopped_since.split("(")[1].split(" GMT)")[0]
                stopped_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                days = age_days(stopped_dt)
            except (IndexError, ValueError):
                pass
            if days < STOPPED_DAYS_THRESHOLD:
                continue
            findings.append({
                "resource_id": inst["InstanceId"],
                "resource_type": "ec2_instance",
                "reason": f"stopped_{days}_days",
                "age_days": days,
                "estimated_monthly_cost_usd": round(EC2_T3_MICRO_PER_HOUR * HOURS_PER_MONTH, 2),
                "tags": {k: tags.get(k) for k in REQUIRED_TAGS},
                "suggested_action": "terminate",
                "safe_to_auto_delete": False,
            })
    return findings


def find_unassociated_eips(ec2) -> list[dict]:
    response = ec2.describe_addresses()
    findings = []
    for addr in response["Addresses"]:
        if "AssociationId" in addr:
            continue
        tags = tags_as_dict(addr.get("Tags", []))
        findings.append({
            "resource_id": addr.get("AllocationId", addr.get("PublicIp")),
            "resource_type": "elastic_ip",
            "reason": "unassociated",
            "age_days": 0,
            "estimated_monthly_cost_usd": round(EIP_PER_HOUR * HOURS_PER_MONTH, 2),
            "tags": {k: tags.get(k) for k in REQUIRED_TAGS},
            "suggested_action": "release",
            "safe_to_auto_delete": False,
        })
    return findings


def find_missing_tags(ec2) -> list[dict]:
    findings = []
    response = ec2.describe_instances()
    for reservation in response["Reservations"]:
        for inst in reservation["Instances"]:
            tags = tags_as_dict(inst.get("Tags", []))
            missing = missing_required_tags(tags)
            if missing:
                findings.append({
                    "resource_id": inst["InstanceId"],
                    "resource_type": "ec2_instance",
                    "reason": f"missing_tags:{','.join(missing)}",
                    "age_days": 0,
                    "estimated_monthly_cost_usd": 0.0,
                    "tags": {k: tags.get(k) for k in REQUIRED_TAGS},
                    "suggested_action": "tag",
                    "safe_to_auto_delete": False,
                })
    vol_response = ec2.describe_volumes()
    for vol in vol_response["Volumes"]:
        tags = tags_as_dict(vol.get("Tags", []))
        missing = missing_required_tags(tags)
        if missing:
            findings.append({
                "resource_id": vol["VolumeId"],
                "resource_type": "ebs_volume",
                "reason": f"missing_tags:{','.join(missing)}",
                "age_days": 0,
                "estimated_monthly_cost_usd": 0.0,
                "tags": {k: tags.get(k) for k in REQUIRED_TAGS},
                "suggested_action": "tag",
                "safe_to_auto_delete": False,
            })
    return findings


# ── delete actions ────────────────────────────────────────────────────────────

def delete_finding(ec2, finding: dict) -> None:
    rid = finding["resource_id"]
    rtype = finding["resource_type"]
    tags_raw = ec2.describe_volumes(VolumeIds=[rid])["Volumes"][0].get("Tags", []) if rtype == "ebs_volume" else []
    tags = tags_as_dict(tags_raw)
    if is_protected(tags):
        print(f"  SKIP {rid} — Protected=true")
        return
    if rtype == "ebs_volume" and finding["reason"] == "unattached":
        ec2.delete_volume(VolumeId=rid)
        print(f"  DELETED volume {rid}")
    elif rtype == "elastic_ip":
        ec2.release_address(AllocationId=rid)
        print(f"  RELEASED EIP {rid}")
    elif rtype == "ec2_instance" and "stopped" in finding["reason"]:
        ec2.terminate_instances(InstanceIds=[rid])
        print(f"  TERMINATED instance {rid}")
    else:
        print(f"  SKIP {rid} — no auto-delete action for reason '{finding['reason']}'")


# ── report ────────────────────────────────────────────────────────────────────

def build_report(findings: list[dict]) -> dict:
    total_waste = sum(f["estimated_monthly_cost_usd"] for f in findings)
    return {
        "scan_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id": ACCOUNT_ID,
        "region": REGION,
        "summary": {
            "total_orphans": len(findings),
            "estimated_monthly_waste_usd": round(total_waste, 2),
        },
        "findings": findings,
    }


def write_report(report: dict) -> None:
    with open("report.json", "w") as f:
        json.dump(report, f, indent=2)
    with open("report.md", "w") as f:
        f.write(f"# Cost Janitor Report\n\n")
        f.write(f"**Scanned:** {report['scan_timestamp']}  \n")
        f.write(f"**Region:** {report['region']}  \n")
        f.write(f"**Total orphans:** {report['summary']['total_orphans']}  \n")
        f.write(f"**Estimated monthly waste:** ${report['summary']['estimated_monthly_waste_usd']:.2f}\n\n")
        if not report["findings"]:
            f.write("No orphaned resources found.\n")
            return
        f.write("## Findings\n\n")
        f.write("| Resource ID | Type | Reason | Age (days) | Est. Cost/month |\n")
        f.write("|---|---|---|---|---|\n")
        for finding in report["findings"]:
            f.write(
                f"| {finding['resource_id']} "
                f"| {finding['resource_type']} "
                f"| {finding['reason']} "
                f"| {finding['age_days']} "
                f"| ${finding['estimated_monthly_cost_usd']:.2f} |\n"
            )


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    dry_run = not args.delete

    ec2 = make_client("ec2")

    findings = []
    findings.extend(find_unattached_ebs(ec2))
    findings.extend(find_long_stopped_instances(ec2))
    findings.extend(find_unassociated_eips(ec2))
    findings.extend(find_missing_tags(ec2))

    report = build_report(findings)
    write_report(report)

    if args.delete and not dry_run:
        print(f"\nRunning in DELETE mode — {len(findings)} finding(s) to process")
        for finding in findings:
            delete_finding(ec2, finding)
    else:
        print(f"\nDry-run complete — {len(findings)} orphan(s) found")
        print("Report written to report.json and report.md")

    if dry_run and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
