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

## Backlog
- P1: Before & After PDF report generator, local trades finder (search), multiple projects
- P2: Supplier price benchmark lookup, stakeholder share link, milestones/timeline
