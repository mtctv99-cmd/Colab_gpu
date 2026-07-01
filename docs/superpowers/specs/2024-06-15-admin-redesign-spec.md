# Frontend Admin Panel Redesign Spec

## 1. Context and Goals
The current Admin page (`/app/admin/page.tsx`) is a monolithic file (~850 lines) rendering all tabs (Dashboard, Accounts, Users, Voices, API Keys, Tasks) in a single massive component. This is difficult to maintain, scale, and does not leverage Next.js App Router properly.

**Goals:**
- Break down the monolith into a structured `/admin/*` routing system.
- Implement a dedicated Admin Sidebar Layout.
- Refresh the UI to a modern, structured Admin panel standard.
- Preserve all existing functionality (fetching from FastAPI, actions, Sonner toasts).

## 2. Architecture & File Structure
We will adopt a Nested Layout architecture in Next.js 15:

```
src/app/
└── admin/
    ├── layout.tsx            # Contains the sidebar and top navigation
    ├── page.tsx              # Overview / Dashboard / Stats
    ├── accounts/
    │   └── page.tsx          # Google Accounts & Workers Management
    ├── tasks/
    │   └── page.tsx          # TTS Tasks History & Retries
    ├── users/
    │   └── page.tsx          # Users, Balances, and API Keys
    ├── voices/
    │   └── page.tsx          # Voice Samples CRUD
    └── settings/             # System config / Variables (placeholder for future expansion)
        └── page.tsx
```

## 3. UI/UX Approach
- **Layout:** A persistent collapsible sidebar on the left, main content area on the right.
- **Components:** Extract repetitive UI elements into `src/components/admin/`:
  - `StatCard.tsx`: For Bento Grid dashboard items.
  - `DataTable.tsx` or specialized tables for Workers, Users, etc.
  - `Sidebar.tsx`: Navigation links.
- **Styling:** TailwindCSS 4 + `motion` (framer-motion). We will keep styling consistent with the existing theme but improve spacing, borders, and empty states.

## 4. Migration Plan (Step-by-Step)
1.  **Create Layout & Sidebar:** Setup `src/app/admin/layout.tsx` and the `Sidebar` component.
2.  **Dashboard Route:** Move the `Stats` and `Overview Tasks` view to `src/app/admin/page.tsx`.
3.  **Accounts Route:** Move `WorkerAccount` list and Actions (Start/Stop/Relogin) to `src/app/admin/accounts/page.tsx`.
4.  **Users Route:** Move User list, Balance Edit, and API Key management to `src/app/admin/users/page.tsx`.
5.  **Voices Route:** Move Voice upload/list to `src/app/admin/voices/page.tsx`.
6.  **Cleanup:** Remove the old monolithic `page.tsx` code.

## 5. Security & Auth
Auth checks remain the same: check `localStorage.getItem("token")` and `user.role === "admin"`. If invalid, redirect to `/login`. This check will run in the `layout.tsx` or custom hook to protect all child routes.
