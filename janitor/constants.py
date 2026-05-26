# Pricing source: https://aws.amazon.com/ebs/pricing/ (us-east-1, as of 2026)
EBS_GP3_PER_GB_MONTH = 0.08  # $0.08 per GB-month for gp3 volumes

# Pricing source: https://aws.amazon.com/ec2/pricing/on-demand/ (us-east-1, Linux)
EC2_T3_MICRO_PER_HOUR = 0.0104  # $0.0104 per hour for t3.micro on-demand

# Pricing source: https://aws.amazon.com/vpc/pricing/
EIP_PER_HOUR = 0.005  # $0.005 per hour for an unattached Elastic IP

HOURS_PER_MONTH = 730  # AWS billing assumes 730 hours per month
