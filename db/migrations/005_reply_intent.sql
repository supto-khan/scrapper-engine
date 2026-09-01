-- Reply Intent Classification: Adds reply_intent and intent_confidence to outreach_messages
ALTER TABLE outreach_messages 
ADD COLUMN reply_intent ENUM('positive_interest', 'not_interested', 'out_of_office', 'neutral_question', 'unknown') NULL AFTER status,
ADD COLUMN intent_confidence FLOAT NULL AFTER reply_intent;
