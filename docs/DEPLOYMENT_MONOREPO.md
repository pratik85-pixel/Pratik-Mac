## Monorepo layout

This GitHub repo is a **monorepo**: backend + mobile frontend live in one repository, but they are still **built and deployed separately**.

- **Backend (Railway)**: repo root (this directory)
- **Frontend (Expo)**: `frontend/`

---

## Primary workflow (recommended)

| Component | Method | Notes |
|-----------|--------|-------|
| **Backend** | Railway (cloud) | Auto-deploys on push to `main` |
| **Frontend** | Android Studio (local) | Build release APK, install on phone — no cloud, no Metro server needed |

This setup gives you a **standalone APK** that talks directly to the Railway backend. No laptop Wi‑Fi, no EAS build minutes, no running Metro.

---

## Backend deployment (Railway, production)

Assumption: backend deploys via **Railway GitHub integration** (no `railway up` from local).

- **Trigger**: push to `main`
- **Build/start**: uses repo root `Dockerfile` / `start.sh` (Railway service configured to this repo)
- **Migrations**: run `alembic upgrade head` as part of the deploy pipeline/startup (preferred), or via Railway "Run Command".

### Post-deploy checks

- Health: `GET /health` should return `{"status":"ok", ...}`
- If a migration was added, confirm it was applied (Railway logs or DB schema).

---

## Frontend deployment

Frontend is an Expo app under `frontend/`. It is deployed independently of Railway.

### Primary: Android Studio (local release APK)

This is the **recommended** way to build and run the app. It produces a **standalone APK** with JS bundled inside — no Metro server, no EAS cloud, no laptop required after install.

#### First-time setup

```bash
cd frontend
cp .env.example .env          # edit EXPO_PUBLIC_API_URL to your Railway backend
npm install                   # installs deps + applies patch-package fixes
npx expo prebuild --platform android
```

#### Build release APK

1. Open **`frontend/android`** in Android Studio (**File → Open**).
2. Wait for Gradle sync to complete.
3. **View → Tool Windows → Build Variants** → change `:app` from `debug` to `release`.
4. **Build → Build Bundle(s) / APK(s) → Build APK(s)**.
5. Click **locate** in the notification to find `app-release.apk`.

#### Install on phone

- **USB:** `adb install -r app/build/outputs/apk/release/app-release.apk`
- **Or:** Copy APK to phone and tap to install (enable "Install unknown apps" if prompted).

The app now runs standalone and talks directly to your Railway backend.

#### Terminal alternative (no Android Studio UI)

```bash
cd frontend/android
NODE_ENV=production ./gradlew assembleRelease
# APK at: app/build/outputs/apk/release/app-release.apk
```

---

### Alternative A: EAS Cloud build

Use when you need a production-signed build for Play Store or distribution. Slower and uses EAS build minutes.

```bash
cd frontend
eas build --platform android --profile production
```

Notes:
- API URL is set via `frontend/eas.json` env (`EXPO_PUBLIC_API_URL`).

### Alternative B: Local Metro on LAN (dev client)

Use for rapid JS iteration during development. Requires laptop + phone on the same Wi‑Fi.

```bash
cd frontend
caffeinate -i npx expo start --dev-client --lan -c
```

Notes:
- Metro serves JS from your laptop; the phone must stay connected.
- Not suitable for "install and forget" usage.

---

### Android Studio troubleshooting

- **API URL:** Local Gradle builds pick up **`frontend/.env`** (see [`.env.example`](../frontend/.env.example)). Rebuild after changing env.
- **Release signing:** Configure a release keystore under **Build → Generate Signed App Bundle or APK** (first time) or add `signingConfigs` in Gradle; keep keystores out of git.
- **When to re-run `prebuild`:** After upgrading Expo, adding native modules, or changing plugins in `app.json`.
- **Gradle can't find `node`:** Set **`NODE_BINARY=`** in **`frontend/android/local.properties`** (absolute path from `which node`). Also ensure **`frontend/android/gradle.properties`** has **`-DNODE_BINARY=...`** in `org.gradle.jvmargs` (same path). Run **`cd frontend && npm install`** after clone to apply patches.
- **`:expo` pointed at wrong folder:** Run **`cd frontend && npm install`** and sync again.

---

## Common gotchas

- Do **not** commit `frontend/node_modules/` or `.expo/` (local caches).
- Railway and EAS are independent: a backend deploy does not rebuild the app binary, and an EAS build does not redeploy the API.
