# Location 2FA

Location-aware multi-factor authentication built with Next.js App Router, Supabase JS v2, and TypeScript.

## Getting started

```bash
cd location-2fa
npm install
cp .env.example .env.local
npm run test
npm run dev
```

## Crypto module

`lib/crypto.ts` provides the location verification primitives used during login:

- HMAC-SHA256 binding of coordinates, session ID, and timestamp
- Haversine distance checks with a default 2 km verification threshold
- URL-safe one-time verification tokens

Unit tests live alongside the module in `lib/crypto.test.ts`.

## Supabase

Browser and server Supabase clients are configured under `lib/supabase/` using `@supabase/supabase-js` v2 and `@supabase/ssr`.
