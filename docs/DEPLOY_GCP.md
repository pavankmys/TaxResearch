# Deploying TaxResearch to Google Cloud

This guide is for the project owner. It covers the one-time setup, and then the everyday steps.

**Status:** the scripts, the workflow and the compose file are written and checked for syntax,
and the logic of `deploy.sh`, `verify.sh` and `db-init.sh` was exercised against stand-ins. **Nothing
has run yet against a real Google Cloud project, a real VM or a real database.** Do the first
deploy together with the maintainer. Expect to fix small things.

## How it fits together

```
You click "Run workflow" in GitHub
   |  builds the api, worker and web images, pushes them to Artifact Registry
   |  copies a few scripts to the VM and runs deploy.sh there (through an IAP tunnel)
   v
Compute Engine VM (Debian 13, rootless Podman)           Cloud SQL for PostgreSQL (private IP)
   web   (127.0.0.1:3000)  --->  api (127.0.0.1:8000)  --->  database, TLS required
   worker (reads the job queue)                              (no database container on the VM)
   documents on a volume on the VM's disk
```

- Nothing is open to the internet. You reach the web app through an **IAP tunnel** to your own computer.
- Settings and passwords live in **Secret Manager**, never in the repository or in GitHub.
- GitHub signs in to Google Cloud without any stored key (Workload Identity Federation, limited to this repository).
- A deploy pulls the new images, upgrades the database, restarts, and **checks health**. If the check fails, it goes back to the previous version.

## Before you start

1. A Google Cloud project where you are an owner.
2. The Compute Engine VM, running **Debian 13**, in the same VPC network as Cloud SQL.
3. A Cloud SQL for PostgreSQL instance with a **private IP**, and the password of its `postgres` user.
   (If you do not know it: Cloud console, your instance, Users, `postgres`, Change password.)
4. The VM can reach the internet to install packages and pull images (an external IP, or Cloud NAT).
5. The VM was created with **access scope "Allow full access to all Cloud APIs"** (`cloud-platform`).
   Otherwise it cannot read Secret Manager or Artifact Registry. `bootstrap.sh` checks this and prints the fix.
6. This repository, with `.github/workflows/deploy.yml` **on the default branch (`main`)**.
   GitHub only shows a workflow in the Actions tab once it is on the default branch.

## One-time setup

### 1. Run the bootstrap in Cloud Shell

Open Cloud Shell in the Google Cloud console, get this repository there, and run:

```bash
git clone https://github.com/pavankmys/TaxResearch.git && cd TaxResearch
bash infra/gcp/bootstrap.sh
```

It asks a few questions (press Enter for the default shown in brackets), then creates:
the image repository, a deploy account for GitHub, the keyless GitHub sign-in, the permissions,
a firewall rule that lets only Google's IAP service reach SSH, and the two secrets.

It asks for three things at hidden prompts, and shows none of them:
the first admin's password, and the Cloud SQL `postgres` password (each typed twice).
It generates the JWT secret and the application database password itself.

It is safe to run again. It only adds things and asks before adding a new secret version.

### 2. Add seven variables in GitHub

At the end the script prints seven lines such as `GCP_PROJECT = ...`. None of them is secret.
In GitHub: **Settings, Secrets and variables, Actions, Variables tab, New repository variable**,
and add each one: `GCP_PROJECT`, `GCP_REGION`, `GCP_ZONE`, `GCP_VM`, `GCP_WIF_PROVIDER`,
`GCP_DEPLOY_SA`, `AR_REPO`.

### 3. Prepare the VM (once)

Run these two commands in Cloud Shell, from the repository folder (the bootstrap prints them with your values filled in):

```bash
gcloud compute scp infra/gcp/vm-setup.sh VM_NAME:~ --zone ZONE --project PROJECT --tunnel-through-iap
gcloud compute ssh VM_NAME --zone ZONE --project PROJECT --tunnel-through-iap --command "sudo bash ~/vm-setup.sh"
```

It installs Podman and the Google Cloud CLI, creates a limited user called `taxresearch` that runs the
containers, and makes the containers start again after a reboot.

### 4. First deploy

In GitHub: **Actions, "Deploy to GCP", Run workflow**. Leave the tag empty to use the commit.

The first run takes longer than later ones: it builds the images, then on the VM it **sets up the database
by itself** (creates the application role and database, and turns on the four PostgreSQL extensions the
app needs), runs the migrations, and creates the first admin user from the values you gave the bootstrap.

When it finishes, the run's summary shows the tunnel command.

## Everyday use

**Open the app.** In a terminal on your computer (needs the `gcloud` tool and permission on the project):

```bash
gcloud compute start-iap-tunnel VM_NAME 3000 --local-port=3000 --zone ZONE --project PROJECT
```

Leave it running and open <http://localhost:3000>. Sign in with the admin email and password from the bootstrap.
Chrome, Edge and Firefox keep the sign-in on `localhost`. If Safari does not, see the table below.

**Deploy an update.** Merge your changes to `main`, then Actions, "Deploy to GCP", Run workflow.
If the new version fails its health check, the old version is started again and the run is marked failed.
The database is **not** rolled back: migrations only go forward, so keep them backward compatible.

**Go back to the previous version by hand.**

```bash
gcloud compute ssh VM_NAME --zone ZONE --project PROJECT --tunnel-through-iap \
  --command "sudo -iu taxresearch /opt/taxresearch/deploy.sh --rollback"
```

**Look at logs.** On the VM (`gcloud compute ssh ... --tunnel-through-iap`):

```bash
sudo tail -n 100 /opt/taxresearch/deploy.log          # the last deploy
sudo -iu taxresearch podman logs --tail 100 taxresearch-api   # also taxresearch-web, taxresearch-worker
sudo -iu taxresearch podman ps                         # what is running, and its health
```

**Check health by hand.** `sudo -iu taxresearch /opt/taxresearch/verify.sh`

## Backups

- **Database:** use Cloud SQL automated backups and point-in-time recovery (Cloud console, your instance, Backups). Check that they are on.
- **Uploaded documents:** they are on the VM's disk (the `taxresearch` user's Podman volume `taxresearch_objects`).
  Set up a **snapshot schedule** for the VM's disk (Compute Engine, Disks, your disk, Create snapshot schedule).
  Deleting the VM together with its disk deletes the documents.

## Changing secrets

The VM can read the secrets but not change them. Change them from Cloud Shell.

- **Application settings, JWT secret, application database password, first-admin values:**
  run `bash infra/gcp/bootstrap.sh` again and answer `y` when it asks to add a new version of `taxresearch-env`.
  It generates a new JWT secret and database password. Then run the deploy workflow: the deploy notices the
  database password changed, runs the database setup again (which sets the new password), and restarts.
  Everyone is signed out when the JWT secret changes.
- **Cloud SQL `postgres` password** (after changing it in the Cloud console):

  ```bash
  read -rs -p "New postgres password: " P; echo
  printf '%s' "$P" | gcloud secrets versions add taxresearch-db-admin --data-file=- --project PROJECT
  unset P
  ```

- **A person's password in the app:** change it in the app (admin users page). The `ADMIN_*` values are only used to
  create the very first admin; changing them later does nothing to an existing admin.

## When something goes wrong

| What you see | Likely cause | What to do |
| --- | --- | --- |
| Workflow stops at "Check the repository variables" | A GitHub variable is missing | Add the variable named in the message (step 2). |
| "Sign in to Google Cloud" fails | The GitHub variables are wrong, or the bootstrap was not run for this repository | Compare `GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA` with the bootstrap output. The provider only accepts the repository you gave the bootstrap. |
| Copy or SSH step fails | The IAP firewall rule or the VM tag is missing, or the deploy account lacks a role | Run the bootstrap again (it repairs missing items). Check the VM has the network tag `taxresearch`. |
| Deploy log says it cannot read a secret | The VM's access scope is too narrow, or the VM account cannot read the secrets | See "Before you start", item 5. Run the bootstrap again. |
| "Failed to pull" an image | The VM account may not read the image repository, or the tag does not exist | Run the bootstrap again. Check the workflow's build steps passed. |
| "Database setup failed" | Wrong Cloud SQL IP, the VM cannot reach it, or the `postgres` password is wrong | Check the private IP in the secret, that the VM and Cloud SQL share a VPC, and the password in `taxresearch-db-admin`. |
| `/ready` returns 503 | The API cannot reach the database | Same checks. `DATABASE_URL` must end with `?sslmode=require`. |
| "Migrations failed" | A migration has an error | Read the end of `deploy.log`. The running version keeps running. Fix the migration and deploy again. |
| Health check fails after "Services started" | A container is crashing | `podman ps` and `podman logs` for the container (see Everyday use). The deploy has already gone back to the previous version if there was one. |
| You sign in but land on the sign-in page again (Safari) | Safari does not accept secure cookies over `http://localhost` | Use Chrome, Edge or Firefox. As a last resort set `COOKIE_SECURE=false` in the secret: the tunnel is still encrypted and nothing is public. |
| The tunnel command is refused | You lack the IAP tunnel role, or the firewall rule is missing | Ask a project owner for `IAP-secured Tunnel User` on the VM. |

## Not covered yet

- Not tested against a real project (see the top). Treat the first deploy as a rehearsal.
- One VM only. No load balancer, no second copy, no automatic failover.
- Deploys start only from the button. Automatic deploys after a green build can be added later.
- Monitoring and alerts are not set up. Container output goes to Cloud Logging by default on Compute Engine if the logging agent is installed.
- The `postgres` password stays readable by the VM's account (it is needed whenever the database is set up again). To remove that access after the first deploy:
  `gcloud secrets remove-iam-policy-binding taxresearch-db-admin --member serviceAccount:VM_SERVICE_ACCOUNT --role roles/secretmanager.secretAccessor`.
  Later deploys then skip the setup unless the application password changed.
