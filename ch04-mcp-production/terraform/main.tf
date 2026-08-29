// Excerpt — full module in code/terraform/. The two load-bearing pieces are
// the Object Lock'd audit bucket (Article 12 / EASA traceability / FAA §6.3)
// and the stateless ECS service.

resource "aws_s3_bucket" "audit" {
  bucket              = var.audit_bucket_name
  object_lock_enabled = true
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    default_retention {
      mode  = "COMPLIANCE"
      years = 7 // match longest applicable regulatory retention
    }
  }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration { status = "Enabled" } // required for Object Lock
}

resource "aws_ecs_service" "mcp" {
  name            = "mcp-server"
  cluster         = aws_ecs_cluster.platform.id
  task_definition = aws_ecs_task_definition.mcp.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.private_subnets
    security_groups = [aws_security_group.mcp.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp.arn
    container_name   = "mcp"
    container_port   = 8080
  }
}

variable "audit_bucket_name" {
  type    = string
  default = "self-healing-mcp-audit"
}

variable "private_subnets" {
  type    = list(string)
  default = []
}
