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
