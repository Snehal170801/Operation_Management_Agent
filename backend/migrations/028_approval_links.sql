-- One-click decisions from the email: a link made for ONE person and ONE approval. Only a hash of the secret is stored.

IF OBJECT_ID('dbo.ApprovalLinks', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ApprovalLinks (
        link_id        UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        approval_id    UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Approvals(approval_id),
        user_id        UNIQUEIDENTIFIER NOT NULL,
        token_hash     CHAR(64)         NOT NULL,
        created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        expires_at     DATETIME2        NOT NULL,
        used_at        DATETIME2        NULL,
        used_action    NVARCHAR(20)     NULL,     -- approve | refuse
        used_ip        NVARCHAR(64)     NULL,
        revoked_at     DATETIME2        NULL      -- replaced by a newer link, or the approval was decided another way
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_ApprovalLinks_token_hash')
    CREATE UNIQUE INDEX UX_ApprovalLinks_token_hash ON dbo.ApprovalLinks(token_hash);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_ApprovalLinks_approval')
    CREATE INDEX IX_ApprovalLinks_approval ON dbo.ApprovalLinks(approval_id);
GO
