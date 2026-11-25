-- Core tables for the Operations Agent (case backbone)
-- Applied by scripts/migrate.py to the database named in SQL_DATABASE


IF OBJECT_ID('dbo.Cases', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Cases (
        case_id         UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        requester_id    NVARCHAR(100)    NOT NULL,
        stage           NVARCHAR(50)     NOT NULL DEFAULT 'created',
        status          NVARCHAR(20)     NOT NULL DEFAULT 'open', -- open | closed | rejected
        summary         NVARCHAR(MAX)    NULL,
        created_at      DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- Every state change and every agent decision gets logged here.
-- This is what the Human Review "reasoning trace" is built from later.
IF OBJECT_ID('dbo.CaseEvents', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.CaseEvents (
        event_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
        case_id         UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES dbo.Cases(case_id),
        event_type      NVARCHAR(100)    NOT NULL, -- e.g. 'case.created', 'purchase_request.created'
        agent_name      NVARCHAR(100)    NULL,     -- which agent raised this event
        payload         NVARCHAR(MAX)    NULL,     -- JSON blob with details / reasoning
        created_at      DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_CaseEvents_case_id')
BEGIN
    CREATE INDEX IX_CaseEvents_case_id ON dbo.CaseEvents(case_id);
END
GO
