CREATE TABLE file_owners (
    file_id TEXT NOT NULL,
    assistant_id UUID,
    thread_id UUID,
    PRIMARY KEY (file_id),
    FOREIGN KEY (assistant_id) REFERENCES assistant(assistant_id) ON DELETE SET NULL,
    FOREIGN KEY (thread_id) REFERENCES thread(thread_id) ON DELETE SET NULL
);
