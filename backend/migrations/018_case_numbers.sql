-- Short, readable case numbers (REQ-2026-0007): numbered in order within each year, never reused.

IF COL_LENGTH('dbo.Cases', 'case_number') IS NULL
    ALTER TABLE dbo.Cases ADD case_number NVARCHAR(20) NULL;
GO

-- One row per year holding the last number handed out. Taking the next number is a single UPDATE, so the
-- row lock makes it safe when two requests arrive at the same moment, and it rolls back with the case.
IF OBJECT_ID('dbo.CaseCounters', 'U') IS NULL
    CREATE TABLE dbo.CaseCounters ([year] INT NOT NULL PRIMARY KEY, last_no INT NOT NULL);
GO

-- Number the cases that already exist, oldest first, restarting at 1 each year.
;WITH n AS (
    SELECT case_id, YEAR(created_at) AS y,
           ROW_NUMBER() OVER (PARTITION BY YEAR(created_at) ORDER BY created_at, case_id) AS rn
    FROM dbo.Cases WHERE case_number IS NULL
)
UPDATE c SET case_number = CONCAT('REQ-', n.y, '-', CASE WHEN n.rn < 10000 THEN RIGHT(CONCAT('000', n.rn), 4) ELSE CAST(n.rn AS NVARCHAR(10)) END)
FROM dbo.Cases c JOIN n ON n.case_id = c.case_id;
GO

MERGE dbo.CaseCounters AS t
USING (SELECT YEAR(created_at) AS y, COUNT(*) AS cnt FROM dbo.Cases GROUP BY YEAR(created_at)) AS s ON t.[year] = s.y
WHEN MATCHED AND t.last_no < s.cnt THEN UPDATE SET last_no = s.cnt
WHEN NOT MATCHED THEN INSERT ([year], last_no) VALUES (s.y, s.cnt);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Cases_case_number')
    CREATE UNIQUE INDEX UX_Cases_case_number ON dbo.Cases(case_number) WHERE case_number IS NOT NULL;
GO
