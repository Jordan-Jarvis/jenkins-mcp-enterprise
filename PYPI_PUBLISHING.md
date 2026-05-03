# PyPI Publishing Guide

This document explains how to publish the Jenkins MCP Server to PyPI so users can install it with `pip install jenkins-mcp-enterprise`.

## 🚀 Quick Overview

Users will be able to install your package with:
```bash
pip install jenkins-mcp-enterprise
```

And run it with:
```bash
jenkins_mcp_enterprise --config config/mcp-config.yml
```

## 📋 Setup Requirements

### 1. PyPI Account Setup
1. Create account at https://pypi.org/account/register/
2. Create account at https://test.pypi.org/account/register/ (for testing)
3. Enable 2FA on both accounts

### 2. GitHub Repository Setup (Trusted Publishing - Recommended)

**This is the SECURE way - no need to store API tokens!**

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. Fill in:
   - **PyPI Project Name**: `jenkins-mcp-enterprise`
   - **Owner**: `Jordan-Jarvis`
   - **Repository name**: `jenkins-mcp-enterprise`
   - **Workflow filename**: `publish.yml`
   - **Environment name**: `pypi`

4. Repeat for Test PyPI at https://test.pypi.org/manage/account/publishing/
   - **Environment name**: `test-pypi`

### 3. GitHub Environment Setup
1. Go to your repo Settings → Environments
2. Create environment named `pypi`
3. Create environment named `test-pypi`
4. (Optional) Add protection rules like requiring manual approval

## 🧪 Testing the Publishing Process

### Option 1: Test with Manual Workflow
1. Go to Actions tab in your GitHub repo
2. Click "Publish to PyPI" workflow
3. Click "Run workflow"
4. Check "Publish to Test PyPI instead of PyPI"
5. Click "Run workflow"

This will publish to https://test.pypi.org where you can verify everything works.

### Option 2: Test Local Build
```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# Check the package
twine check dist/*

# Upload to Test PyPI (requires API token)
twine upload --repository testpypi dist/*
```

## 🚀 Production Publishing

### Automated (Recommended)
1. Create a new release on GitHub:
   - Go to Releases → Create a new release
   - Tag: `v1.0.0` (must match version in pyproject.toml)
   - Title: `v1.0.0`
   - Description: Release notes
   - Click "Publish release"

2. The workflow will automatically:
   - Build the package
   - Run tests
   - Publish to PyPI

### Manual Workflow
1. Go to Actions → "Publish to PyPI"
2. Click "Run workflow"
3. Leave "Publish to Test PyPI" unchecked
4. Click "Run workflow"

## 📦 Package Structure

Your package includes:
- **Main module**: `jenkins_mcp_enterprise/`
- **Entry point**: `jenkins_mcp_enterprise` command
- **Dependencies**: All required packages for Jenkins, MCP, AI features
- **Diagnostic config**: Bundled diagnostic parameters

## 🔧 Version Management

Update version in `pyproject.toml`:
```toml
version = "1.0.3"  # Increment for each release
```

Version format: `MAJOR.MINOR.PATCH`
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

## ⚠️ Important Notes

1. **Email in pyproject.toml**: Update `your.email@domain.com` to your real email
2. **Package name**: `jenkins-mcp-enterprise` is reserved once published
3. **GPL v3 License**: Make sure you're comfortable with GPL v3 requirements
4. **Dependencies**: Heavy dependencies (sentence-transformers, qdrant-client) will increase install time

## 🐛 Troubleshooting

### "Package already exists"
- You can't republish the same version
- Increment version number in `pyproject.toml`

### "Authentication failed"
- Check Trusted Publishing setup
- Verify environment names match exactly
- Make sure you're publishing from the correct repository

### "Build failed"
- Check that all files are included in git
- Verify pyproject.toml syntax
- Ensure LICENSE file exists

## 📈 After Publishing

1. **Verify installation**:
   ```bash
   pip install jenkins-mcp-enterprise
   jenkins_mcp_enterprise --help
   ```

2. **Update README** with pip install instructions

3. **Monitor PyPI page**: https://pypi.org/project/jenkins-mcp-enterprise/

4. **Track downloads**: PyPI provides download statistics

## 🔄 Updating the Package

1. Make changes to code
2. Update version in `pyproject.toml`
3. Test locally
4. Create new GitHub release
5. Workflow automatically publishes new version

## 💡 Tips

- Always test on Test PyPI first
- Keep a CHANGELOG.md file
- Use semantic versioning
- Consider pre-releases for beta features (e.g., `1.1.0b1`)
