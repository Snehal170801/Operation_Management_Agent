-- Authentication: users and refresh-token sessions

IF OBJECT_ID('dbo.Users', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Users (
        user_id          UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        username         NVARCHAR(100)    NOT NULL,
        display_name     NVARCHAR(150)    NULL,
        password_hash    NVARCHAR(200)    NOT NULL,            -- bcrypt, never the password
        role             NVARCHAR(30)     NOT NULL DEFAULT 'user', -- admin | user
        is_active        BIT              NOT NULL DEFAULT 1,
        failed_attempts  INT              NOT NULL DEFAULT 0,
        locked_until     DATETIME2        NULL,
        last_login_at    DATETIME2        NULL,
        created_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Users_username')
BEGIN
    CREATE UNIQUE INDEX UX_Users_username ON dbo.Users(username);
END
GO

-- One row per issued refresh token. Only a SHA-256 of the token is stored.
-- Tokens are single-use (rotated on refresh); replaying a revoked one revokes
-- the user's whole session family.
IF OBJECT_ID('dbo.RefreshTokens', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.RefreshTokens (
        token_id      UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        user_id       UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Users(user_id),
        token_hash    CHAR(64)         NOT NULL,
        family_id     UNIQUEIDENTIFIER NOT NULL,
        persistent    BIT              NOT NULL DEFAULT 0,   -- "remember me"
        expires_at    DATETIME2        NOT NULL,
        revoked_at    DATETIME2        NULL,
        user_agent    NVARCHAR(300)    NULL,
        ip_address    NVARCHAR(64)     NULL,
        created_at    DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_RefreshTokens_token_hash')
BEGIN
    CREATE UNIQUE INDEX UX_RefreshTokens_token_hash ON dbo.RefreshTokens(token_hash);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_RefreshTokens_user_id')
BEGIN
    CREATE INDEX IX_RefreshTokens_user_id ON dbo.RefreshTokens(user_id);
END
GO
