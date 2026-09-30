terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }    
  }

  backend "s3" {
    bucket         = "inbox-janitor-tfstate-prod"
    key            = "inbox-janitor/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "inbox-janitor-tf-locks"
    encrypt        = true
  }
}