ALTER TABLE file_owners
ADD COLUMN file_path TEXT;

ALTER TABLE file_owners
ADD COLUMN file_hash TEXT;

ALTER TABLE file_owners
ADD COLUMN embedded BOOLEAN;

UPDATE file_owners
SET file_path = file_id,
    file_hash = '',
    embedded = TRUE;

-- Need this to set the file_path column as unique
CREATE TABLE file_owners_temp (
    file_id TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    embedded BOOLEAN NOT NULL,
    assistant_id TEXT,
    thread_id TEXT,
    PRIMARY KEY (file_id),
    FOREIGN KEY (assistant_id) REFERENCES assistant(assistant_id) ON DELETE SET NULL,
    FOREIGN KEY (thread_id) REFERENCES thread(thread_id) ON DELETE SET NULL
);

INSERT INTO file_owners_temp (file_id, file_path, file_hash, embedded, assistant_id, thread_id)
SELECT file_id, file_path, file_hash, embedded, assistant_id, thread_id FROM file_owners;

DROP TABLE file_owners;
ALTER TABLE file_owners_temp RENAME TO file_owners;