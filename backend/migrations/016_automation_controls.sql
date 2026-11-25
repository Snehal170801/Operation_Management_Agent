-- Safety controls for the automatic agents: a pause switch, and a lock so only one
-- server instance runs the background worker at a time.

IF OBJECT_ID('dbo.SystemSettings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.SystemSettings (
        setting_key    NVARCHAR(100) NOT NULL PRIMARY KEY,
        setting_value  NVARCHAR(500) NOT NULL,
        updated_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_by     NVARCHAR(254) NULL
    );
END
GO

IF OBJECT_ID('dbo.WorkerLeases', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.WorkerLeases (
        name        NVARCHAR(50)  NOT NULL PRIMARY KEY,
        holder      NVARCHAR(100) NOT NULL,
        expires_at  DATETIME2     NOT NULL
    );
END
GO
