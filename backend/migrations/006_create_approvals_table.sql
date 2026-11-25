
IF OBJECT_ID('dbo.Approvals', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Approvals (
        approval_id         UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        case_id             UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        approval_type       NVARCHAR(50)     NOT NULL,
        -- pending | approved | rejected | auto_approved | superseded
        status              NVARCHAR(20)     NOT NULL,
        reasons             NVARCHAR(MAX)    NULL,
        decided_by          NVARCHAR(255)    NULL,
        decision_note       NVARCHAR(MAX)    NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        decided_at          DATETIME2        NULL
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Approvals_case_id')
BEGIN
    CREATE INDEX IX_Approvals_case_id ON dbo.Approvals(case_id);
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_Approvals_status')
BEGIN
    CREATE INDEX IX_Approvals_status ON dbo.Approvals(status);
END
GO
