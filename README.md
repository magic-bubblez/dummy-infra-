
## Overview

orphaned resources are the biggest cause of wastage of financial resources for any company. this repo contains a small slice of the fix - infrastructure as code that applies cleanly on LocalStack, a cost janitor that finds orphaned resources and estimates what they're costing, and a CI/CD workflow that enforces it on every PR so the waste can't silently creep back.


## How to run locally

```bash
git clone git@github.com:magic-bubblez/dummy-infra.git
cd dummy-infra

# Start LocalStack
docker run --rm -d -p 4566:4566 --name localstack localstack/localstack:4.14.0

# Apply the Terraform stack
cd terraform
tflocal init
tflocal apply -auto-approve

# Verify resources
awslocal ec2 describe-vpcs --query "Vpcs[*].{ID:VpcId,CIDR:CidrBlock}" --output table
awslocal ec2 describe-instances --query "Reservations[*].Instances[*].{ID:InstanceId,Type:InstanceType,State:State.Name}" --output table
awslocal s3 ls
awslocal ec2 describe-volumes --query "Volumes[*].{ID:VolumeId,State:State}" --output table

# Run the Cost Janitor (dry-run)
cd ../janitor
pip install -r requirements.txt
python janitor.py --dry-run
```

## Architecture

```
                          Internet
                              │
                    ┌─────────────────┐
                    │ Internet Gateway │
                    └────────┬────────┘
                             │
          ┌──────────────────────────────────────┐
          │           VPC 10.20.0.0/16           │
          │                                      │
          │  ┌───────────────┐  ┌─────────────┐  │
          │  │ Subnet 1      │  │ Subnet 2    │  │
          │  │ 10.20.1.0/24  │  │ 10.20.2.0/24│  │
          │  │ us-east-1a    │  │ us-east-1b  │  │
          │  │               │  │             │  │
          │  │ ┌───────────┐ │  │ ┌─────────┐ │  │
          │  │ │EC2 web-1  │ │  │ │EC2 web-2│ │  │
          │  │ │ t3.micro  │ │  │ │t3.micro │ │  │
          │  │ └───────────┘ │  │ └─────────┘ │  │
          │  └───────────────┘  └─────────────┘  │
          │                                      │
          │  Security Group: 80/443 open,        │
          │  22 from configurable CIDR           │
          └──────────────────────────────────────┘

 
```



