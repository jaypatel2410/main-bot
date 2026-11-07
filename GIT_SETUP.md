# Push the main bot to GitHub (private)

Do this once. `.gitignore` already keeps out `.env` (keys), logs, caches, `.db` files, backtest runs and build output.
Your backtest notes (`backtest\*\notes.json`) ARE included.

## 1. Install Git (once)
Download from https://git-scm.com/download/win and install with the default options. Then open a NEW PowerShell window:
```
git --version
git config --global user.name  "Jay Patel"
git config --global user.email "jaykumarpatel2410@gmail.com"
```

## 2. Create the repository on GitHub
github.com -> New repository -> name `lh-bot` -> **Private** -> do NOT add a README / .gitignore -> Create.

## 3. First push (from the bot folder)
```
cd "C:\Users\jayku\OneDrive\Desktop\test vs code\test vs code\main bot version 3.12"
git init
git branch -M main
git add .
git status
```
Check the `git status` list: `.env` must NOT be in it (only `.env.example`). Then:
```
git commit -m "Kestrel 3.12.1 - folder layout"
git remote add origin https://github.com/<your-github-name>/lh-bot.git
git push -u origin main
```
The first push opens a GitHub sign-in window - sign in and it is remembered.

## 4. Every time you change something
```
cd "C:\Users\jayku\OneDrive\Desktop\test vs code\test vs code\main bot version 3.12"
git add .
git commit -m "what changed, e.g. 3.12.2 colors tab"
git push
```

## Useful
- `git log --oneline` - the history of your commits
- `git diff` - what changed since the last commit
- Restore one file to the last commit: `git checkout -- core\bot\orders.py`
- A key pushed by mistake: delete the key at TradeZero / Discord right away and make a new one (removing it from git
  does not make it secret again).
