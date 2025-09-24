# Cory_dev: proposed repo structure for implementation 
/diagram/                    # DOT/Mermaid sources (render to svg for docs)
/sql/                        # migrations & seeds
/app/
  db.py                      # Supabase client + queries
  models.py                  # pydantic state models
  policies.py                # pacing/backoff/attempts
  orchestrator_graph.py      # LangGraph brain (3 nodes)
  adapters/
    voice_synthflow.py
    sms_n8n.py
    email_n8n.py
  webhooks/
    synthflow.py
    campaign.py
  enrollment_agent.py
  campaign_builder.py
  scheduler.py               # cron worker / job runner
  handoff.py                 # Slack/Ticket integration
/tests/
  unit/
  integration/
  fixtures/
docs/README.md               # embeds rendered SVGs
