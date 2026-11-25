-- When an item counts as "low" (min_level) and how many to bring it back up to (target_level). Both empty = never marked low.

IF COL_LENGTH('dbo.Stock', 'min_level') IS NULL
    ALTER TABLE dbo.Stock ADD min_level INT NULL;
GO

IF COL_LENGTH('dbo.Stock', 'target_level') IS NULL
    ALTER TABLE dbo.Stock ADD target_level INT NULL;
GO
