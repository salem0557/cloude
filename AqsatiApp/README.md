# أقساطي (Aqsati) — Installments & Subscriptions Tracker

iOS app for the Saudi market: track every installment (Tabby, Tamara, bank,
store) and subscription (Shahid, Netflix, gym…) in one place, see your total
monthly obligations, and get reminders before payments are due.

**Business model:** free up to 5 active commitments → premium subscription
(~15 SAR/month or ~99 SAR/year) for unlimited commitments.

## What's included (v1)

- **Dashboard** — total monthly obligations, remaining installment debt,
  active/completed lists with progress bars
- **Add commitment** — installment (N payments) or subscription (recurring),
  weekly/monthly/quarterly/yearly, provider quick-chips (تابي، تمارا، البنك)
- **Mark paid** — swipe or tap; advances the due date, completes finished
  installments automatically
- **Reminders** — local notifications 1/2/3/7 days before each due date (set
  in Settings)
- **Paywall** — StoreKit 2, free tier limited to 5 active commitments,
  product IDs `aqsati.premium.monthly` and `aqsati.premium.yearly`
- **Arabic-first** (RTL) with full English localization; data stays 100% on
  device — no backend, no server costs, simple privacy story

## How to build

You need a Mac with Xcode 15+ (own, borrowed, or a cloud Mac such as
MacinCloud/Scaleway). The project file is generated with
[XcodeGen](https://github.com/yonaskolb/XcodeGen):

```bash
brew install xcodegen
cd AqsatiApp
xcodegen generate
open Aqsati.xcodeproj
```

Then in Xcode: select the `Aqsati` scheme → pick a simulator → **Run** (⌘R).

To run on a real iPhone or upload to the App Store, set your Apple Developer
team in *Signing & Capabilities* (requires the $99/year Apple Developer
account).

### Without XcodeGen (manual)

Create a new iOS App project in Xcode (SwiftUI, Swift), delete its template
`ContentView.swift`, then drag the `Aqsati/` folder contents into the project
navigator (check "Copy items if needed"). Add `ar` as a localization under
*Project → Info → Localizations*.

## App Store Connect setup (for the paywall to work)

1. Create the app in App Store Connect with bundle ID `com.salem0557.aqsati`.
2. Under **Monetization → Subscriptions**, create a subscription group
   "Aqsati Premium" with two auto-renewable subscriptions:
   - `aqsati.premium.monthly` — 15 SAR / month
   - `aqsati.premium.yearly` — 99 SAR / year
3. Enroll in the **App Store Small Business Program** (15% commission
   instead of 30%).

Until these products exist, the paywall shows a friendly "not configured
yet" message — the rest of the app works fully.

## Roadmap (after v1 ships)

- v1.1 — edit commitments, payment history log, iCloud sync (CloudKit)
- v1.2 — home screen widgets (next payment / monthly total)
- v1.3 — charts (spending over time), export to CSV
- v2.0 — salary day awareness, "can I afford this?" calculator
