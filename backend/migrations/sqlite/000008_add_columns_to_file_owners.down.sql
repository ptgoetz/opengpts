ALTER TABLE file_owners
DROP COLUMN file_hash;

ALTER TABLE file_owners
DROP COLUMN embedded;

CREATE TABLE file_owners_temp (
    file_id TEXT NOT NULL,
    assistant_id TEXT,
    thread_id TEXT,
    PRIMARY KEY (file_id),
    FOREIGN KEY (assistant_id) REFERENCES assistant(assistant_id) ON DELETE SET NULL,
    FOREIGN KEY (thread_id) REFERENCES thread(thread_id) ON DELETE SET NULL
);

INSERT INTO file_owners_temp (file_id, assistant_id, thread_id)
SELECT file_path, assistant_id, thread_id FROM file_owners;

DROP TABLE file_owners;
ALTER TABLE file_owners_temp RENAME TO file_owners;