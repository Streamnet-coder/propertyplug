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
