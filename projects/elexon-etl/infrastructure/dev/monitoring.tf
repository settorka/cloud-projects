locals {
  # Query validation is deferred until the first pilot creates the log table.
  event_query = <<-KQL
    ContainerAppConsoleLogs_CL
    | extend event = parse_json(Log_s)
    | where tostring(event.application) == "elexon-etl"
  KQL
  health_queries = {
    failures = {
      frequency   = "PT5M"
      window      = "PT30M"
      enabled     = true
      query       = <<-KQL
        ${local.event_query}
        | where tostring(event.event) in ("invocation_failed", "partition_failed", "coverage_warning")
      KQL
      description = "Elexon processing failure or publication-slot warning in the last 30 minutes. Inspect structured logs and the run manifest. Startup/kill failures without application logs are detected by the daily missing-success rule."
    }
    missing_daily_success = {
      frequency   = "PT1H"
      window      = "P2D"
      enabled     = var.schedule_cron != null
      query       = <<-KQL
        ${local.event_query}
        | where TimeGenerated > ago(27h)
        | where tostring(event.event) == "invocation_succeeded" and tostring(event.command) == "daily"
        | summarize Successes=count()
        | where Successes == 0
      KQL
      description = "No full daily Elexon invocation succeeded within 27 hours. Covers a missed schedule, image-pull failure, killed job, or missing logs. Enabled only with a daily schedule; allow an initial successful daily invocation before enabling."
    }
  }
}

resource "azurerm_monitor_action_group" "operator" {
  name                = "ag-elexon-etl-dev"
  resource_group_name = azurerm_resource_group.project.name
  short_name          = "elexon"
  email_receiver {
    name                    = "operator"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "health" {
  for_each                = var.image_digest == null ? {} : local.health_queries
  name                    = "elexon-${each.key}"
  resource_group_name     = azurerm_resource_group.project.name
  location                = azurerm_resource_group.project.location
  scopes                  = [azurerm_log_analytics_workspace.logs.id]
  evaluation_frequency    = each.value.frequency
  window_duration         = each.value.window
  severity                = 2
  enabled                 = each.value.enabled
  description             = each.value.description
  skip_query_validation   = true
  auto_mitigation_enabled = true
  criteria {
    query                   = each.value.query
    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }
  action {
    action_groups = [azurerm_monitor_action_group.operator.id]
  }
  tags = local.tags
}
