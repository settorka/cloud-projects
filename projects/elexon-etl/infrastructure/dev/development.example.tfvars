subscription_id      = "00000000-0000-0000-0000-000000000000"
storage_account_name = "replaceelexondata"
registry_name        = "replaceelexonregistry"
operator_object_id   = "00000000-0000-0000-0000-000000000000"
alert_email          = "you@example.com"
# Foundation apply first; then build/push image and set its real digest.
image_digest = null
dataset      = "BOTH"
source_date  = "2025-01-01"
# Keep manual until pilot acceptance. Schedule requires source_date = null.
schedule_cron = null
