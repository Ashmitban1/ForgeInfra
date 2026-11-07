# Put this project on GitHub

The ZIP has files at its **root** (not a nested extra folder). Extract it and move its contents to your repo root. You can also upload the extracted folder contents with GitHub's **Add file → Upload files** interface; use `git` for preserving full nested structure reliably.

## If your remote repository already exists
```powershell
git clone https://github.com/YOUR-USERNAME/FactoryOS.git
# Copy ALL extracted files into the cloned FactoryOS folder, preserving folders
cd FactoryOS
git add .
git commit -m "Initialize FactoryOS starter"
git push origin main
```
Use your actual GitHub URL. If your default branch isn't `main`, push `git branch --show-current` instead.

## If you're starting from an extracted folder
```powershell
git init
git add .
git commit -m "Initialize FactoryOS starter"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/FactoryOS.git
git push -u origin main
```
The remote should be empty. If it has commits, clone it first to avoid non-fast-forward errors.

## Collaborate with branches
```powershell
git switch -c person1-backend
# Make your changes
git add .
git commit -m "Implement hardware ingestion"
git push -u origin person1-backend
```
Person 2 can use `person2-agents`, Person 3 `person3-frontend`. Open PRs to merge with `main`.
