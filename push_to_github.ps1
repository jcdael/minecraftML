# push_to_github.ps1
# This script will help you push the Minecraft ML project to GitHub
# Run this script in PowerShell as Administrator

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Minecraft ML - GitHub Push Script" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Git is installed
Write-Host "Checking Git installation..." -ForegroundColor Yellow
try {
    $gitVersion = git --version
    Write-Host "✓ Git is installed: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Git is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Git from: https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host "Or run: winget install --id Git.Git -e --source winget" -ForegroundColor Yellow
    exit 1
}

# Check if we're in the right directory
$currentDir = Get-Location
Write-Host "Current directory: $currentDir" -ForegroundColor Yellow

# Check for .git folder
if (Test-Path ".git") {
    Write-Host "✓ Git repository already initialized" -ForegroundColor Green
} else {
    Write-Host "Initializing Git repository..." -ForegroundColor Yellow
    git init
    Write-Host "✓ Git repository initialized" -ForegroundColor Green
}

# Check for remote
Write-Host "Checking remote configuration..." -ForegroundColor Yellow
$remotes = git remote -v
if ($remotes) {
    Write-Host "Current remotes:" -ForegroundColor Green
    $remotes
} else {
    Write-Host "No remote configured" -ForegroundColor Yellow
}

# Add GitHub remote
$githubUrl = "https://github.com/jcdael/minecraftML"
Write-Host "Adding GitHub remote: $githubUrl" -ForegroundColor Yellow
git remote add origin $githubUrl
Write-Host "✓ Remote added" -ForegroundColor Green

# Check .gitignore
Write-Host "Checking .gitignore file..." -ForegroundColor Yellow
if (Test-Path ".gitignore") {
    Write-Host "✓ .gitignore file exists" -ForegroundColor Green
    Write-Host "Contents will exclude:" -ForegroundColor Gray
    Get-Content .gitignore | Where-Object { $_ -notmatch '^#' -and $_ -notmatch '^\s*$' } | ForEach-Object {
        Write-Host "  - $_" -ForegroundColor Gray
    }
} else {
    Write-Host "✗ No .gitignore file found" -ForegroundColor Red
}

# Stage all files
Write-Host "Staging all files..." -ForegroundColor Yellow
git add .
Write-Host "✓ Files staged" -ForegroundColor Green

# Show what will be committed
Write-Host "Files to be committed:" -ForegroundColor Yellow
git status --short

# Create commit
$commitMessage = "Initial commit: Minecraft ML project with AI agent, brain, adapter, and server components"
Write-Host "Creating commit with message: '$commitMessage'" -ForegroundColor Yellow
git commit -m "$commitMessage"
Write-Host "✓ Commit created" -ForegroundColor Green

# Push to GitHub
Write-Host "Pushing to GitHub..." -ForegroundColor Yellow
Write-Host "This may ask for your GitHub credentials" -ForegroundColor Yellow
git push -u origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Successfully pushed to GitHub!" -ForegroundColor Green
} else {
    Write-Host "Trying to push to master branch..." -ForegroundColor Yellow
    git push -u origin master
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Successfully pushed to GitHub!" -ForegroundColor Green
    } else {
        Write-Host "✗ Push failed. You may need to:" -ForegroundColor Red
        Write-Host "  1. Check your GitHub credentials" -ForegroundColor Yellow
        Write-Host "  2. Create the repository on GitHub first" -ForegroundColor Yellow
        Write-Host "  3. Check your internet connection" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Repository URL: $githubUrl" -ForegroundColor White
Write-Host "Project includes:" -ForegroundColor White
Write-Host "  - AI Brain (Python ML agent)" -ForegroundColor Gray
Write-Host "  - Adapter (Node.js bridge)" -ForegroundColor Gray
Write-Host "  - Minecraft Server" -ForegroundColor Gray
Write-Host "  - Configuration and scripts" -ForegroundColor Gray
Write-Host "  - Documentation" -ForegroundColor Gray
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Visit $githubUrl to see your repository" -ForegroundColor White
Write-Host "2. Set up GitHub credentials if prompted" -ForegroundColor White
Write-Host "3. Consider adding a README.md description" -ForegroundColor White