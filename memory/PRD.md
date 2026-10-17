# My Builder App — PRD

## Original problem statement
Build a mobile app from the "My Builder App | Project, Cost & BRRR Management for Developers & DIYers" HTML SaaS prototype (UK renovation + BRRR investing; teal/cyan/orange brand, Inter font).

## User choices
- JWT email/password auth
- Basic vs Pro: simulated plan toggle (Pro features locked on Basic) + real Stripe one-time Pro upgrade (£19, test mode)
- AI cost estimates (Claude Sonnet 5.5 via Emergent LLM key)
- Camera/gallery uploads to Emergent Object Storage (seed data uses placeholder images)

## Architecture
- Backend: FastAPI + MongoDB (motor), Pydantic BaseDocument models, bcrypt + PyJWT, emergentintegrations (LLM, Stripe), Emergent object storage
- Frontend: Expo SDK 57, expo-router, react-query, 4 tabs (Home, Budget, Team, Media; NativeTabs on iOS 26+), modal forms, Lucide icons, Inter font

## Implemented (2026-06)
- Auth (register seeds a demo Nottingham project), 30-day trial
- Home dashboard: hero project card, spend progress, category breakdown, deal snapshot, recent receipts, Add Expense
- Budget: filter chips, line-item CRUD, variance, AI estimate → add items to budget
- Team: trades (call/WhatsApp/email), Pro subcontractor portal & stakeholders
- Media: before/progress/after photo gallery + receipts with photo upload, preview/delete
- BRRR calculator (Pro) with 1/4 mile comparables
- Profile: plan preview toggle, Stripe upgrade with polling, edit project, logout

## Iteration 2 (2026-06)
- PDF progress report (expo-print + expo-sharing): KPIs, budget breakdown, line items, receipts, before/progress/after photos
- Multiple projects: /api/projects list/create/activate/delete; all data scoped per active project; switcher on Home & Profile
- Trades finder: postcodes.io + OpenStreetMap (Overpass with Nominatim fallback), 24h cache, call/WhatsApp/email invite + add to team

## Iteration 3 (2026-06)
- Milestone timeline: 10 default stages per project, status cycle, target dates/notes, Home progress card, included in PDF & live report
- Lender share link: public live HTML report /api/share/{token} (revocable), copy/share/preview, PDF snapshot
- Quote requests: one brief to multiple trades, private public quote form links /api/q/{token}, side-by-side compare (lowest/avg/spread), accept -> adds budget line item

## Iteration 4 (2026-06)
- Report branding (logo + company/contact) on PDF, live share page and quote pages (/api/branding)
- Stage photos: media.milestone_id, before/after per milestone, thumbnails on live report & timeline counts
- Trial CTA on public share/quote pages -> public signup /api/join (signup_source tracked)

## Iteration 5 (2026-06)
- Referral rewards: CTA links carry &by=owner; /api/join credits +30 days trial; /api/referrals + Profile card
- Stage payment schedule vs accepted quotes (overpay blocked), paid sums sync line item actuals
- Snagging list per room with photo/priority/assignee, tick off; snag summary on live report

## Iteration 6 (2026-06)
- Snag share links per assigned trade (/api/snag-links, public /api/s/{token}) — trades mark fixed with photo + note; fix evidence shown in app
- Referral prompt card on Share screen

## Backlog
- P1: Lender comments on live report, snag share link for trades, split server.py into routers
- P2: Supplier price benchmark lookup, stakeholder share link, milestones/timeline

## Maintenance (Jun 2026)
- Test cleanup now guarded: tests/cleanup.py only deletes TEST_-prefixed users and their data; demo referrals/count restored instead of wiped.

## Iteration 7 (Jun 2026)
- Backend refactor: server.py split into core.py, models.py, deps.py, storage.py, html_utils.py, seed.py and routes/* (auth, projects, budget, contacts, media, ai, payments, trades, milestones, branding, referrals, share, quotes, stage_payments, snags, shopping, digest). Same API surface.
- Rent Yield: Project.refinance_ltv (75) & refinance_rate (5.5); /api/project returns rent_yield {gross_yield, yield_on_cost, invested, refinance_amount, cash_left_in, monthly_mortgage, monthly_cashflow}; dashboard "Rent & refinance" card; edit fields in project-edit; share report #rent-yield card.
- Weekly Digest: GET /api/digest?week=N (Mon–Sun UTC) → spend (receipts by date + paid stage payments), snags fixed, milestones done, next milestone; dashboard "This week" card + /digest screen with week navigation.
- Shopping List: /api/shopping CRUD, POST /api/shopping/from-line-items, DELETE /api/shopping/checked; /shopping (grouped by merchant, tick off) + /shopping-add modal; entry banner on Budget tab.

## Iteration 8 (Jun 2026)
- /health + /api/health endpoints for deployment health checks.
- Account deletion: DELETE /api/auth/account {password} (rate-limited 5 fails/15min) deletes all user data (projects, items, receipts, media, milestones, quotes, payments, snags, links, shopping, estimates, payment_transactions, files, referrals) then the user. UI: Profile → "Delete account" → /delete-account modal (password + confirm).
- Faster projects list: project_summaries() batches with 3 aggregate queries; indexes on project_id/user_id; frontend prefetches projects on dashboard (staleTime 30s).
- Shareable weekly digest: GET/POST/DELETE /api/digest/share; public page /api/d/{token}?week=N (prev/next nav, branding, trial CTA ref=digest). UI: DigestShareCard on /digest.
- Shopping purchase logging: POST /api/shopping/{id}/purchase {amount} → ticks item + creates Receipt (category from linked line item); un-ticking deletes that receipt. UI: PurchaseSheet when ticking an item.

- App renamed to **Builder Assist** (app.json name, in-app brand mark, PDF report, all public HTML pages, Stripe return page).

## Iteration 9 (Jun 2026)
- PDF downloads (expo-print): Dashboard progress report (dashboard-pdf-button), Budget estimate (budget-pdf-button), Snag report (snags-pdf-button), BRRR analysis (brrr-pdf-button, Pro). src/report.ts printPdf/brandHeader/doc helpers.
- Data export: GET /api/export → ZIP of CSVs (account + 10 data types). Delete-account screen has "Download all data (ZIP)" + Progress/Budget/Snags PDF buttons. src/export.ts (expo-file-system File.downloadFileAsync on native, blob download on web).
- Budget variance alerts: /api/line-items returns linked_spend (receipts linked to line item, e.g. shopping purchases), spent, alert ('over' >100%, 'near' >=90%). Budget tab pills + banner + "Alerts" filter; dashboard variance-alert-card; purchase endpoint returns alert → toast.
- Weekly digest email (Emergent managed Resend, EMAIL_FROM_NAME=Builder Assist): GET/PUT /api/digest/settings {recipients ≤10, auto}, POST /api/digest/send-now (2-min cooldown), background scheduler every 15 min sends last week's update Mondays ≥08:00 Europe/London once per ISO week. WhatsApp: wa.me share button on DigestShareCard.

- Lender Report Pack: share-report screen 'Lender report pack' card (lender-pack-button) → one PDF: cover summary (valuation, refi, money left in, yield, contents) + progress + budget estimate + BRRR analysis (Pro only). report.ts shareLenderPack/calcBrrr (shared with brrr.tsx; BRRR now defaults LTV/rate from project).

## Iteration 10 (Jun 2026)
- Snag Sign-Off: snag_signoffs {project_id, assignee_lc, owner/trade: {name, path(SVG), width, height, signed_at}, snag_count}. GET/POST /api/snag-signoffs (owner, requires all assignee snags fixed), DELETE /api/snag-signoffs/{assignee}; public /api/s/{token} shows sign-off canvas when all fixed, POST /api/s/{token}/sign. New/reopened snags void the sign-off. App: SignoffPanel on /snags (SignaturePad via react-native-svg + PanResponder). Snag PDF includes sign-off section; titled "SIGNED-OFF SNAGGING REPORT" when all trades fully signed.
- Stakeholder message log: db.messages; GET /api/stakeholders (team contacts + digest partners with count/last activity), GET/POST /api/messages. Auto-logged: weekly digest emails (sent/failed), snag link views (1/day), snags fixed, trade sign-offs, quote submissions (inbound); client logs snag link sends, quote request sends, team call/WhatsApp/email. UI: Team header "Message log" → /stakeholders → /stakeholder timeline with Call/WhatsApp/Email actions.
- User also mentioned "separate domain email for stakeholders (investors, partners)" — needs user's own domain + Resend API key; not built (pending clarification).

## Iteration 11 (Jun 2026)
- Company email (compliant "own domain"): managed email can't send FROM a custom address (platform guardrail; BYO Resend keys disallowed), so a verified company address is used as Reply-To and company name appears in email body. GET/POST/DELETE /api/email-settings (POST sends verification email, 3/hour), public GET /api/verify-email/{token}. owner_reply_to() used by digest emails. UI: CompanyEmailCard on /branding; reply-to hint on DigestEmailCard.
- Sign-off notifications: trade signing on /api/s/{token}/sign emails owner (verified company email else account email) via notify_owner_signoff.
- Trade ratings: POST /api/trade-ratings {assignee, stars 1-5, tags(TAGS), comment} (requires owner sign-off; upsert per project+trade), GET /api/trade-ratings?project=active, GET /api/trusted-trades (avg across projects). UI: Rate button/stars in SignoffPanel (RatingSheet), stars + sort on Team trades, "Your trusted trades" (≥4★) on trades finder intro.

## Iteration 12 (Jun 2026)
- Project document library: routes/documents.py — POST /api/documents (multipart file + title + doc_type from 14 UK types + notes; pdf/doc/docx/xls/xlsx/csv/txt/jpg/png/heic/webp, ≤20MB, Emergent object storage), GET (?doc_type), PUT, DELETE, GET /documents/{id}/download & /documents/zip (bearer or ?token; zip foldered by type), POST/DELETE /documents/{id}/share → public /api/doc/{token} page + /file download. Included in data export, account deletion, project delete.
- UI: dashboard "Documents" card → /documents (search, type filter chips with counts, download, share, delete, Download all ZIP) → /document-form modal (expo-document-picker). DocumentShareSheet: share/copy link, send to stakeholder via WhatsApp/email (logged in message log), turn off link.
- Added src/utils/upload.ts uploadForm (Blob via expo/fetch on native) and switched src/upload.ts uploadAsset to it (fixes real-device FormData issue).

## Iteration 13 (Jun 2026)
- Expiry reminders: documents.expires_on (YYYY-MM-DD, upload Form/PUT); expiry_status ('expired' | 'soon' ≤30 days | 'ok') + days_left; GET /api/documents/expiring. Dashboard expiry-alert-card; document row badges; expiry field in document-form.
- Document folder links: POST/GET/DELETE /api/doc-folders {title, doc_ids, origin_url}; public /api/f/{token} (list + per-file /d/{doc_id} + /zip). UI: Documents "Select" mode → FolderSheet; folder button lists/revokes links.
- Stakeholder portal: owners invite (POST /api/portal-members {name,email,role,handle?,doc_ids,digest,origin_url}; PUT/DELETE/resend) → global handle name@buildassist (portal_handles). Stakeholders sign in at web page /api/portal with email or handle + 6-digit email code (POST /api/portal/request-code, /api/portal/verify; HMAC-hashed, 10-min TTL, 5 attempts, 3 sends/15min, no enumeration). Portal JWT signed with JWT_SECRET+'|portal' and typ=portal (cannot access owner APIs). GET /api/portal/me, /api/portal/projects/{pid}?week=, /api/portal/projects/{pid}/documents/{did}. Owner UI: /portal-access (from Documents header).

## Iteration 14 (Jun 2026)
- Portal activity: db.portal_activity (login, view throttled 1/hr, download with doc) → GET /api/portal-activity; UI Activity tab on /portal-access (download summary per doc + timeline).
- Portal questions: stakeholders POST/GET /api/portal/projects/{pid}/questions (10/hr), owner emailed; owner GET /api/portal-questions, POST /api/portal-questions/{id}/reply → stakeholder emailed; logged in message log. UI Questions tab with reply; portal web page #portal-questions card.
- Over-budget emails: routes/alerts.check_over_budget (on line item create/update, shopping purchase/untick) emails owner once when spend > budget (over_notified flag, reset when back under).
- Expiry emails: run_expiry_reminders in 15-min scheduler: once when doc enters 30-day window and once after expiry (flags store expires_on so renewals re-arm); grouped per owner.
- User asked to link app to Buildassist.com custom domain → routed to support (platform/deployment question).

## Deployment Readiness (Jun 2026)
- Deployment health check: PASS. Lint clean. Old test files/reports (iterations 1-12, backend_test.py) removed.

## Spend Trend Charts (Jun 2026)
- GET /api/line-items/trend: cumulative daily spend (line item actuals by created_at + linked receipts by date) vs total budget, per active project.
- Budget tab: 'Spend vs budget' line chart + 'By category' bars (src/components/spend-charts.tsx). Tested iteration 17.

## Multi-currency & Land (Jun 2026)
- Per-project currency (GBP, EUR, USD, CAD, AUD, NZD, ZAR, AED, NGN, INR); frontend gbp()/sym() follow active project; backend money() uses CURRENCY contextvar.
- Land property type: plot_size/unit, planning_status, intended_use; hides rent/BRRR.
- /api/portfolio converts totals to user home_currency via Frankfurter live rates (cached 6h in db.fx_rates). Portfolio card on My projects. Tested iteration 18.

## Land Uplift, Portfolio Map, Planning Tracker (Jun 2026)
- Project: value_without_planning/value_with_planning, lat/lon/pin_manual (manual pin) + auto Nominatim geocode cached (geocoded_for).
- /api/planning CRUD (planning_apps), days_to_decision; dashboard PlanningCard reminder (no email). LandUplift card.
- /api/portfolio/map + portfolio-map screen (Leaflet/OSM; WebView native, iframe web).
- Fixed: backend EMERGENT_LLM_KEY was stale after fork -> object storage 401; updated. Tested iteration 19.

## Map Filters (Jun 2026)
- /api/portfolio/map returns country (Nominatim addressdetails, accept-language=en, cached). Map screen filters: type, currency, country + clear. Tested iteration 20.

## Stakeholder access code + password (Jun 2026)
- portal_accounts {email, code_lookup HMAC, password_hash bcrypt, failed, locked_until, reset}. Invite emails BA-XXXX-XXXX-XXXX-XXXX code until password set.
- /portal/activate, /portal/login-password (5 fails -> 15 min lock), /portal/password-reset/request|confirm. Email OTP login kept.
- Team: member.company + 'Add a teammate' (copies role/docs/digest). password_set shown to owner.

## Map filter totals + Team leads (Jun 2026)
- Map: FilterTotals bar (purchase/value/budget/spent for filtered pins; native currency if single else home currency via portfolio rates).
- Portal: member.is_lead (requires company), invited_by. Lead endpoints /portal/projects/{pid}/team GET/POST/DELETE (same owner+project+company; can't remove leads/self). Activity kinds team_invite/team_remove.

## Portal access end dates (Jun 2026)
- portal_members.expires_on (YYYY-MM-DD, access through that day). active_q() filters login/_resolve/_account_by_code/portal_me; _membership 403 when expired. Teammates inherit lead's end date. Owner UI AccessEndPicker (presets/date/no end).

## Expiry heads-up (Jun 2026)
- GET /api/portal-members/expiring (all owner projects; ends within 7 days or ended last 7), POST /api/portal-members/{id}/extend {days} (from max(today,end)). ExpiringAccessCard on dashboard + portal-access.

## Co-owners + 3-tier pricing (Jun 2026)
- co_owners {owner_id, email}. deps.effective(): when user.acting_owner_id set (via /projects/{id}/activate on shared project) and still co-owner, current_user returns OWNER User with co-owner's active_project_id + real_id. real_user dependency for /auth/me, account delete, plan, payments, export, referrals, projects list/create/activate/delete, portfolio/map, co-owner mgmt.
- /projects lists own + shared (shared, owner_name). Co-owners can't delete projects (403).
- /co-owners GET/POST/DELETE, /co-owners/shared-with-me, DELETE /co-owners/shared/{owner_id}.
- Pricing: PRO_TIERS monthly £19.99 (31d), yearly £199 (365d), lifetime £499; Stripe one-off checkout with tier; pro_until lapses to basic in load_user. /payments/tiers.

## Co-owners + 3-tier pricing (Jun 2026)
- co_owners {owner_id, email}. deps.effective(): when user.acting_owner_id set (via /projects/{id}/activate on shared project) and still co-owner, current_user returns OWNER User with co-owner's active_project_id + real_id. real_user dependency for /auth/me, account delete, plan, payments, export, referrals, projects list/create/activate/delete, portfolio/map, co-owner mgmt.
- /projects lists own + shared (shared, owner_name). Co-owners can't delete projects (403).
- /co-owners GET/POST/DELETE, /co-owners/shared-with-me, DELETE /co-owners/shared/{owner_id}.
- Pricing: PRO_TIERS monthly 19.99 GBP (31d), yearly 199 (365d), lifetime 499; Stripe one-off checkout with tier; pro_until lapses to basic in load_user. /payments/tiers.

## Activity log + Lead doc requests (Jun 2026)
- server.py middleware -> routes/activity.log_write: successful POST/PUT/DELETE on project areas logged to project_activity {owner_id, project_id, actor_id/name, is_owner, action}. GET /api/project-activity; screen project-activity.
- portal_doc_requests: lead POST/GET /portal/projects/{pid}/doc-requests; owner GET /portal-doc-requests, PUT /portal-doc-requests/{id} {status fulfilled|declined, reply, doc_ids} shares docs with requester's company team. DocRequestsPanel in portal-access.
- Auto-renew subscriptions (DONE): routes/subscriptions.py uses user's LIVE STRIPE_SECRET_KEY (backend .env) via stripe SDK, mode=subscription with inline price_data (1999/19900 pence GBP). Lifetime still via emergentintegrations one-time (STRIPE_API_KEY). Sync re-fetches subscription from Stripe (status polling, lapsed-period refresh in deps.load_user, webhook /api/webhook/stripe-subscriptions; STRIPE_WEBHOOK_SECRET empty -> events treated as hints only). Cancel/resume: /payments/subscription/cancel|resume (cancel_at_period_end). Buying lifetime cancels active subscription.

## Billing history + request reminders (Jun 2026)
- GET /api/payments/history (one-off paid txs + Stripe invoices with hosted receipt URL); GET /api/payments/receipt/{session_id}?t=token printable HTML. Screen /billing (profile link).
- Doc requests: days_waiting/overdue(>=3d)/can_remind; lead POST /portal/projects/{pid}/doc-requests/{rid}/remind (3+ days, once/24h, emails owner); owner GET /portal-doc-requests/overdue -> dashboard OverdueRequestsCard.

- Activity filters (Jun 2026): client-side person + area chips on project-activity screen (limit 300).
- Stripe webhook endpoint created via API (we_1URGLVRfIVVOsnJmtQd4HGOC) for preview URL; STRIPE_WEBHOOK_SECRET set; signature verified. Must re-create for deployed URL.

## AI estimate photo + finished design (Jun 2026)
- /ai/estimate accepts photo_path (Claude vision), items have spec + visible; returns id. POST /ai/estimate/{id}/design: Nano Banana (gemini-3.1-flash-image-preview) edits photo or generates, Claude locates pins (x,y - AI estimate photo + finished design: /ai/estimate photo_path, POST /ai/estimate/{id}/design (Nano Banana + Claude pins), DesignHotspots.

## Iteration 30 (Jun 2026)
- Rent & tenancy tracker: /api/rentals?year (tenancies with monthly schedule paid/partial/late/due, arrears; expenses by category; yearly net cashflow + monthly chart). Tenancy CRUD, PUT /rentals/tenancies/{id}/rent/{YYYY-MM}, expense CRUD. Screens: /rentals, /tenancy-form, /rental-expense-form, rent log sheet; dashboard RentalsCard.
- Before/after slider: /compare (pick any before + after/progress photo; ?milestone_id filters to stage). Entry: Media tab "Compare" button, stage photos "Compare before & after".
- Design polish: blurred sticky Add Expense bar, EmptyState rounded icon + optional CTA (Budget/Team), stronger hero scrim.

## Iteration 31 (Jun 2026)
- Manual rent reminders: POST /api/rentals/tenancies/{id}/remind {month} (friendly vs late email, 10-min cooldown, logged in Messages); button in rent log sheet.
- Deposit protected yes/no toggle + warnings; tenancy end ≤60 days alerts; dashboard TenancyAlertsCard.
- Lender pack: Rental income section (YTD received, costs, net, arrears, tenancies, monthly table) + cover KPIs.
- Shareable before/after links: /api/compare-links CRUD, public /api/c/{token} branded slider page with trial CTA; ShareCompare card on /compare.
- Project purpose investment|personal: personal hides BRRR (quick action, profile link, lender pack BRRR), shows Mortgage & equity + Remortgage cards (home_finance in project summary; deposit, mortgage_rate, mortgage_term, mortgage_type, remortgage_ltv). target_type "Home Renovation".

## Iteration 32 (Jun 2026)
- Tenancy renewal: POST /api/rentals/tenancies/{id}/renew (new end date or rolling, optional new rent from date -> rent_changes, renewals history, emails tenant terms). RenewSheet on tenancy cards.
- Auto rent receipts (receipts_auto per tenancy, default on) emailed on rent log when amount changes; logged in Messages.
- Personal mortgage: fixed_rate_end + FixedRateAlertCard (≤90 days / ended); up to 3 remortgage_scenarios with cheapest monthly + best 2-yr (incl. fees) highlights.

## Iteration 33 (Jun 2026)
- Annual rent statements: POST /api/rentals/tenancies/{id}/statement, POST /api/rentals/statements (all), auto every January for previous year (statements_auto per tenancy, rent_statements dedup, statement_scheduler hourly).
- Tenant portal: POST/DELETE /api/rentals/tenancies/{id}/portal; public /api/t/{token} (terms, deposit, rent schedule with year nav, printable receipts /receipt/{YYYY-MM}, repair form -> snag with reported_by + owner email, 10/day limit).
- Overpayment planner (client-side) with monthly slider (@react-native-community/slider) + lump sum on personal-home dashboard.

## Iteration 34 (Jun 2026)
- Repair updates: tenant emailed when a portal-reported repair is marked fixed (owner app or trade link); portal lists repair reports with status.
- Tenant documents: PUT /api/rentals/tenancies/{id}/documents shares Document Library files on the tenant portal (with expiry), download /api/t/{token}/doc/{did}; picker in tenant portal sheet.
- Portfolio rent roll: GET /api/portfolio/rent-roll?year (home-currency totals, per-property + tenants); /rent-roll screen from Projects header.

## Rebrand (Jun 2026)
- App renamed Builder Assist -> PropertyPlug (app.json name, EMAIL_FROM_NAME, all share pages/emails/reports/Stripe product names). Wordmark "PropertyPlug" in Inter-ExtraBoldItalic (assets/fonts) with italic tagline "All landlord needs"; brand icon house-plug.
- Welcome copy refreshed for landlords + renovators (headline, pill, lead, 7 features incl. rent tracker, tenant portal, rent roll).
- New app icon (teal gradient + white house-plug), Android adaptive icon (bg #0f766e), favicon, splash (mark + italic PropertyPlug wordmark + tagline on white).

## Managers (Jun 2026)
- co_owners.project_ids: null = co-owner (all projects), list = manager (full access to chosen projects only). access_filter() in routes/projects.py used by project list, activate, portfolio map, rent roll; deps.effective() pins managers to allowed projects. PUT /api/co-owners/{id} changes scope. UI: /co-owners "Co-owners & managers" with role chips + project picker.

## Manager money permissions (Jun 2026)
- co_owners.money_access (default true). False = tasks only: deps.effective sets owner.no_money; block_money router dependency (budget, quotes, stage_payments, ai, rentals, tenant_portal, share, /project/comparables) returns 403; project summaries zero money fields + money_hidden; PUT /project ignores money keys; rent roll skips. acting_as.money exposed; frontend useCanSeeMoney hides Budget tab, dashboard money cards, receipts, AI/BRRR/share actions.

## Task inbox (Jun 2026)
- GET /api/inbox (routes/inbox.py): open snags, tenant repairs (snags with tenancy_id) and not-done stages due within 30 days/overdue across all accessible projects (own + co-owned + manager-scoped), overdue first. /inbox "My tasks" screen with filters; Home quick action "My tasks"; tapping activates the item's project and opens /snags or /timeline.
- Quick mark fixed: POST /api/inbox/snags/{sid}/fix (multipart note + optional file, real_user + access_filter; sets fixed_by, fix_photo_path, notifies tenant for repairs, logs message + project_activity). QuickFixSheet on My tasks items (inbox-fix-{id}).
- Portal IDs rebranded: stakeholder handles now name@propertyplug (legacy @buildassist still accepted at sign-in), new access codes PP-XXXX-XXXX-XXXX-XXXX (old BA- codes still work). OSM user agent propertyplug/1.0.

## Shareable co-owner invite links (Jun 2026)
- db.co_owner_links {owner_id, token, project_ids (null=co-owner), money_access, expires_at (7 days), used_at}. Owner: GET/POST /api/co-owner-links, DELETE /api/co-owner-links/{id}. Public GET /api/join/{token} preview; POST /api/join/{token} (real_user) claims atomically once -> co_owners row (via_link) + owner email. 404 invalid, 410 used/expired, 400 own link/already has access.
- Frontend: InviteLinks on /co-owners (same role/projects/money choices), /join/[token] landing (accept or sign up/log in with ?next=/join/... which auth.tsx follows).

## Tenant report link + assign to team (Jun 2026)
- Per-property "Report a problem" link (db.report_links): GET/POST/DELETE /api/report-link (active project); public /api/r/{token} form (name, email, phone, room, description, priority, photo) -> snag source=report_link with reporter_*; owner emailed; 20/day per link.
- Assign: GET /api/snag-assignees (co-owners/managers with access to the project + project trade contacts); POST /api/snags/{id}/assign {kind team|trade, id, origin_url} sets assignee + assigned_to + job_token, emails assignee job link /api/job/{token} (issue, photo, mark fixed with photo+note). Fixing notifies the reporter (reporter_email) or tenancy tenant.
- Inbox: report-link snags count as repairs; items have mine flag (assigned to me, team kind), sorted first, "Assigned to me" chip.
- UI: megaphone button on Snagging list -> ReportLinkSheet (WhatsApp/copy/share/turn off); Assign pill on open snag rows -> AssignSheet.
