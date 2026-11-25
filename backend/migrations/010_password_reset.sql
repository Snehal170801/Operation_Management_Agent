-- Password reset by one-time code: users get an email address; codes are stored hashed.

IF COL_LENGTH('dbo.Users', 'email') IS NULL
    ALTER TABLE dbo.Users ADD email NVARCHAR(254) NULL;
GO

-- Unique among users that have one; many users may have none.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Users_email')
    CREATE UNIQUE INDEX UX_Users_email ON dbo.Users(email) WHERE email IS NOT NULL;
GO

IF OBJECT_ID('dbo.PasswordResetOtps', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.PasswordResetOtps (
        otp_id      UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        user_id     UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Users(user_id),
        otp_hash    CHAR(64)         NOT NULL,      -- HMAC of the code, never the code itself
        expires_at  DATETIME2        NOT NULL,
        attempts    INT              NOT NULL DEFAULT 0,
        used_at     DATETIME2        NULL,          -- set when consumed or invalidated
        ip_address  NVARCHAR(64)     NULL,
        created_at  DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_PasswordResetOtps_user_id')
    CREATE INDEX IX_PasswordResetOtps_user_id ON dbo.PasswordResetOtps(user_id, created_at DESC);
GO
