-- Every attachment the system has already read, by a fingerprint of its content, per case: the same file is never sent to the AI twice.
-- (A supplier re-sending the same PDF, or two mail copies of it, is noted on the case instead.)

IF OBJECT_ID('dbo.ReadFiles', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ReadFiles (
        case_id        UNIQUEIDENTIFIER NOT NULL,
        file_hash      CHAR(64)         NOT NULL,
        file_name      NVARCHAR(260)    NULL,
        first_read_at  DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_ReadFiles PRIMARY KEY (case_id, file_hash)
    );
END
GO
