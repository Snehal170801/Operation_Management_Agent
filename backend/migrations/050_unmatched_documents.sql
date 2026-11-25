-- A document a known supplier sent that names no order we can find (no case tag, no PO number we know): kept for a person to attach to the right case.

IF OBJECT_ID('dbo.UnmatchedDocuments', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.UnmatchedDocuments (
        document_id      UNIQUEIDENTIFIER NOT NULL PRIMARY KEY DEFAULT NEWID(),
        from_email       NVARCHAR(320)    NOT NULL,
        vendor_name      NVARCHAR(200)    NULL,
        subject          NVARCHAR(500)    NULL,
        summary          NVARCHAR(600)    NULL,            -- the first words, for the list
        file_names       NVARCHAR(600)    NULL,
        payload          NVARCHAR(MAX)    NOT NULL,        -- JSON {body, attachments:[{name, text, images}]}: enough to read it again when attached
        status           NVARCHAR(20)     NOT NULL DEFAULT 'open',    -- open | attached | dismissed
        case_id          UNIQUEIDENTIFIER NULL,
        handled_by       NVARCHAR(150)    NULL,
        handled_at       DATETIME2        NULL,
        note             NVARCHAR(500)    NULL,
        created_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_UnmatchedDocuments_status')
    CREATE INDEX IX_UnmatchedDocuments_status ON dbo.UnmatchedDocuments (status, created_at DESC);
GO
