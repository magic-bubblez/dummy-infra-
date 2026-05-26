terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }
}

provider "aws" {
  region            = var.aws_region
  access_key        = "test"
  secret_key        = "test"
  s3_use_path_style = true

  endpoints {
    ec2 = "http://localhost:4566"
    s3  = "http://localhost:4566"
    sts = "http://localhost:4566"
  }
}

module "network" {
  source               = "./modules/network"
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  common_tags          = local.common_tags
}

resource "aws_instance" "web" {
  count                  = 2
  ami                    = "ami-00000000"
  instance_type          = "t3.micro"
  subnet_id              = module.network.private_subnet_ids[count.index]
  vpc_security_group_ids = [module.network.security_group_id]

  tags = merge(local.common_tags, {
    Name = "${var.project}-web-${count.index + 1}"
    Tier = "web"
  })
}

resource "aws_s3_bucket" "app_logs" {
  bucket = "${var.project}-${var.environment}-app-logs"
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_ebs_volume" "orphan" {
  availability_zone = var.availability_zones[0]
  size              = 8

  tags = merge(local.common_tags, {
    Name = "${var.project}-orphan-vol"
  })
}
