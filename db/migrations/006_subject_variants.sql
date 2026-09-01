-- A/B Testing: Adds subject_variant column to outreach_messages
ALTER TABLE outreach_messages 
ADD COLUMN subject_variant VARCHAR(10) NULL DEFAULT 'A' AFTER generator_type;
