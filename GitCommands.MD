🧭 Goal

You want to:

Keep your main branch clean and identical to GitHub’s main.

Create a new branch (e.g., ticket_c3.4) for each ticket.

Develop, commit, and push changes only in that branch.

Later open a PR (pull request) to merge back into main.

🧱 1️⃣ Start fresh: update local main from remote main

Always begin by syncing your local main with GitHub’s latest main.

# Switch to your main branch
git checkout main

# Fetch the latest updates from GitHub
git fetch origin

# Merge or fast-forward your local main to match remote main
git pull origin main


✅ Now your local main = origin/main (the latest team version).

🌿 2️⃣ Create a new branch for your new ticket

Use a clear, descriptive name for your branch — e.g.,
ticket_c3.4-new-workflow or feature/c3.4-trigger-logic.

# Create and switch to a new branch in one step
git checkout -b ticket_c3.4


That branch now “branches off” from your freshly updated main.

🧩 3️⃣ Verify you’re on the right branch
git branch


✅ Output example:

  main
* ticket_c3.4


The asterisk (*) means you’re currently working on that branch.

💻 4️⃣ Make your changes and commit locally

After editing code, run:

git status
git add .
git commit -m "C3.4: Implement new workflow trigger logic"


Tip: keep commits small and descriptive — easier for PR reviews later.

🚀 5️⃣ Push your new branch to GitHub
git push -u origin ticket_c3.4


✅ -u links your local branch to the remote branch,
so future pushes can just use git push.

Now GitHub will show your branch and let you open a Pull Request (PR).
