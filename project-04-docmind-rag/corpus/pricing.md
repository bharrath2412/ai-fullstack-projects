# Plans and pricing

DocMind is billed per workspace, per month. Annual billing takes 20% off the list price.
All prices are in USD and exclude local taxes.

## Free

- 1 workspace, 3 members
- 1,000 indexed document pages
- 60 API requests per minute
- 7-day answer history
- Community support only

The Free plan is intended for evaluation and side projects. Indexed pages above the limit are
not searchable until you upgrade or remove documents.

## Team — $24 per seat / month

- Unlimited workspaces
- 25,000 indexed pages per workspace
- 600 API requests per minute
- 90-day answer history
- Email support with a 1 business-day response target
- Shared prompt library and saved searches

Team is the most common plan for product and support teams. Seats are billed monthly in
arrears based on the highest number of active users during the month; a user counts as active
if they signed in or used the API that month.

## Enterprise — custom pricing

- Everything in Team, plus:
- Unlimited indexed pages
- 6,000 API requests per minute, burst 500
- SAML single sign-on (SSO) and SCIM user provisioning — **SSO is only available on
  Enterprise**
- Dedicated VPC or on-premise deployment
- Audit log export and 99.9% uptime SLA
- Named solutions engineer and 1-hour Sev-1 support

Enterprise contracts start at 50 seats. SSO is not sold as an add-on for Team: teams that need
SSO must move to Enterprise.

## Add-ons

| Add-on | Price | Notes |
| --- | --- | --- |
| Extra indexed pages | $12 / 10,000 pages / month | Team only |
| Extended history | $4 / seat / month | 2 years of answer history |
| Premium connectors | $99 / month | Salesforce, Zendesk, Confluence |
| Private model routing | usage-based | Bring your own Azure OpenAI deployment |

## Data retention and exports

- Answer history: 7 days (Free), 90 days (Team), 2 years (Enterprise, extendable).
- Deleted documents are recoverable from the trash for **30 days**, after which they are purged
  from primary storage and backups within a further 14 days.
- Workspace exports are generated as a signed download URL valid for 24 hours. Export retention
  is **30 days**: the export file itself is deleted 30 days after creation, and re-running the
  export is always allowed.
- Audit logs are retained for 400 days on Enterprise and 30 days on Team.

## Billing FAQ

**Do unused seats roll over?** No. Seats are counted per calendar month.

**Can I switch plans mid-month?** Yes. Upgrades are prorated immediately; downgrades take
effect at the next renewal.

**What happens if a payment fails?** The workspace stays readable for 14 days, writes are
disabled after 7 days, and the account is suspended after 21 days. Data is not deleted for 90
days after suspension.
