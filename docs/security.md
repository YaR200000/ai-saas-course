# Lesson 6: Digital Security and Secrets

## 1. What Is a Secret?

A secret is confidential information that provides access to an application, database, API, or another private service.

Secrets must not be published in source code, GitHub repositories, documentation, or logs.

## 2. Secrets in Our Project

Our educational Telegram bot may use the following secrets:

- **BOT_TOKEN** — allows the application to communicate with Telegram Bot API.
- **DATABASE_URL** — contains connection information for PostgreSQL, including database credentials.
- **AI_API_KEY** — will be used to access an AI service in the future.
- **Passwords** — protect accounts and private services.

Currently, AI integration and the PostgreSQL database are planned components of the project.

## 3. Why Secrets Must Be Protected

If a secret becomes public, unauthorized users may gain access to our services.

Possible consequences include:

- Unauthorized control of the Telegram bot.
- Access to confidential database information.
- Modification or deletion of stored data.
- Unexpected API usage and financial costs.
- Compromise of application security.

Secrets should never be hardcoded into Python files or published on GitHub.

## 4. The .env File

The `.env` file stores real environment variables and credentials locally.

Example structure (placeholders only):

```dotenv
BOT_TOKEN=your_telegram_bot_token_here
DATABASE_URL=your_database_url_here
AI_API_KEY=your_ai_api_key_here
```

The real `.env` file must never be committed to Git.

## 5. The .env.example File

The `.env.example` file contains safe placeholders instead of real credentials.

Its purpose is to document which environment variables are required to configure the application.

Unlike `.env`, this file can be committed to GitHub.

## 6. The .gitignore File

The `.gitignore` file tells Git which untracked files should be ignored.

Our project includes these rules:

```gitignore
.env
.env.*
!.env.example
```

These rules prevent ordinary `.env` files from being added accidentally while allowing `.env.example` to be tracked.

Important: `.gitignore` does not automatically remove files that Git already tracks.

## 7. What to Do If a Secret Is Leaked

If a token, password, or connection string is accidentally exposed:

1. Revoke or rotate the compromised credential immediately.
2. Generate a new token or password.
3. Update the local `.env` file with the new value.
4. Remove the exposed credential from the project files.
5. Check Git history and assess whether the credential remains accessible.
6. Review service logs and account activity for unauthorized access.
7. Verify that the application works with the new credentials.

Deleting a secret from the latest commit is not enough because it may remain in Git history.

## 8. Security Rules for Our AI SaaS Project

- Never commit `.env` files.
- Never publish real tokens, passwords, or connection strings.
- Use environment variables instead of hardcoded credentials.
- Keep `.env.example` free of real secrets.
- Review `git status` and `git diff` before committing.
- Check staged changes before every commit.
- Do not print credentials in application logs.
- Rotate credentials immediately if they are exposed.

## Conclusion

Secure secret management is an essential part of developing reliable applications.

Our project uses `.env`, `.env.example`, and `.gitignore` to separate confidential configuration from public source code.

These practices will help us safely connect our Telegram bot to Neon PostgreSQL and future AI services.