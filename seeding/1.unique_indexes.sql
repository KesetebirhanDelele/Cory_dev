-- Match each ON CONFLICT you use in seeds

-- organizations(name)
create unique index if not exists ux_nx_org_name
  on dev_nexus.organizations (name);

-- contacts(org_id, email)
create unique index if not exists ux_nx_contact_org_email
  on dev_nexus.contacts (org_id, email);

-- campaigns(org_id, name)
create unique index if not exists ux_nx_campaign_org_name
  on dev_nexus.campaigns (org_id, name);

-- campaign_steps(campaign_id, order_id)
create unique index if not exists ux_nx_step_campaign_order
  on dev_nexus.campaign_steps (campaign_id, order_id);
