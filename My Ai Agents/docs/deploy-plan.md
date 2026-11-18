# Deployment Plan — CacheCollapse

*A step-by-step plan to put CacheCollapse online. This is a **plan only** — nothing
is deployed until you decide to. Tests: ALL PASSED (see docs/test-report.md).*

## Important first note (read this)

CacheCollapse is a **security demo that attacks its own database on purpose**. So
"deploying" it is not like publishing a normal website:

- **Keep it private.** The dashboard has buttons that launch an attack. Anyone who
  can open it can overload the demo. Only you, your group, and your instructor
  should be able to reach it.
- **It only ever attacks itself.** Everything runs inside its own Docker network.
  It never touches any real/outside system. Keep it that way.
- **Easiest "deployment" is often local.** For the class presentation, running
  `docker compose up` on a laptop and opening `http://localhost:8090` is perfectly
  valid and the safest option. The steps below are for when you want it reachable
  from other machines (e.g. the instructor opening it from their own laptop).

## 1. Where to publish

**A single small cloud virtual machine (VM) running Docker.**
Reason: the VM runs the exact same `docker compose up` you already use — **no code
changes** — and your team/instructor can reach it by the VM's address. A free or
low-cost tier is enough.

Good options (any one):
| Option | Cost | Note |
|---|---|---|
| **Oracle Cloud "Always Free" VM** | Free | Generous free tier (recommended for a student project) |
| AWS EC2 / Azure (student credit) | Free tier | Use a `t3.small`/`B1s` or larger |
| DigitalOcean / Hetzner droplet | ~$6–7/mo | Simplest to set up |

**Size needed:** at least **2 GB RAM, 2 vCPU** (9 containers). 4 GB is comfortable.
A platform that only runs *one* container (Vercel, Netlify, GitHub Pages) will
**not** work — this is a multi-container system.

## 2. What you need first

- A cloud account (one of the above).
- **SSH** to log into the VM (built into Windows PowerShell: `ssh`).
- On the VM: **Docker** and the **Docker Compose plugin** installed.
- Your project folder (this whole `Cache Collapse` directory).
- Optional: a free domain or subdomain if you want a nice URL instead of an IP.

## 3. Steps

1. **Create the VM** in your cloud console (Ubuntu 22.04 LTS, ≥2 GB RAM). Note its
   public IP address.
2. **Log in:** `ssh ubuntu@<VM-IP>` (user name depends on the provider).
3. **Install Docker on the VM:**
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER      # then log out and back in
   ```
4. **Copy the project to the VM.** From your PC, in the project folder:
   ```
   scp -r "C:/Users/Aun Zaidi/Desktop/Cache Collapse" ubuntu@<VM-IP>:~/cachecollapse
   ```
   (Or `git clone` it if you push it to GitHub first.)
5. **Set production values** in `.env` on the VM (see Secrets below) — strong
   passwords, and keep `PUBLIC_PORT=8090`.
6. **Start it:**
   ```
   cd ~/cachecollapse
   docker compose up --build -d
   ```
7. **Open the firewall for ONLY your users.** In the cloud console's firewall /
   security group, allow TCP **8090** (dashboard) and optionally **3000** (Grafana)
   **from your own IP address only**, not from `0.0.0.0/0`. This is the "keep it
   private" step.
8. **Open it:** `http://<VM-IP>:8090` from an allowed machine.

### Optional: a real URL with HTTPS
Point a subdomain at the VM's IP and put **Caddy** in front (it gets a free HTTPS
certificate automatically). This is a nice-to-have, not required for the demo.

## 4. Secrets

All secrets live in the **`.env`** file, which is already in `.gitignore` (never
committed, never in code). Before deploying, change these from their demo defaults:

| Secret | Where | What to do |
|---|---|---|
| `POSTGRES_PASSWORD` | `.env` | Set a strong random password |
| Grafana admin password | `docker-compose.yml` (`GF_SECURITY_ADMIN_PASSWORD`) | Change from `admin`; better, move it into `.env` and reference it |
| Grafana anonymous access | `docker-compose.yml` | For a public-ish deploy, set `GF_AUTH_ANONYMOUS_ENABLED=false` |

Keep `.env` only on the VM and your own PC. Do not paste it into chats, commits, or
screenshots. There are **no third-party API keys** in this project.

## 5. How to check it works

After `docker compose up -d` on the VM:
1. `docker compose ps` — all 9 services show **Up** (`db` shows healthy).
2. Open `http://<VM-IP>:8090` — the dashboard loads; the tab title counter climbs.
3. From the VM, run the test suite against it:
   ```
   python3 tests/test_cachecollapse.py
   ```
   Expect `15 passed, 0 failed`.
4. Click **Start normal traffic**, then **Launch attack** — the graphs react and
   the shop (`/shop.html`) visibly struggles, then recovers with defenses on.

## 6. How to undo / take it down

- **Stop but keep it:** `docker compose down` (on the VM).
- **Stop and wipe all data/volumes:** `docker compose down -v`.
- **Remove completely:** delete the project folder, then **delete the VM** in the
  cloud console so you stop being billed.
- **Roll back a change:** redeploy the previous version (e.g. `git checkout` an
  earlier commit, then `docker compose up --build -d` again).

## Summary of the safe path for your presentation

For the CEP demo, the simplest reliable plan is: **run it locally** on the
presenting laptop (`docker compose up`, open `http://localhost:8090`). Use the
cloud-VM steps above only if someone needs to open it remotely — and if so, lock
the firewall to known IPs and change the default passwords first.
