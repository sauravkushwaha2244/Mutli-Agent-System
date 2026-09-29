-- Supabase Database Schema for ResearchMind History & Auth Integration

CREATE TABLE IF NOT EXISTS public.research_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    topic TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    sources_count INTEGER DEFAULT 0,
    claims_count INTEGER DEFAULT 0,
    credibility_avg NUMERIC(4, 2) DEFAULT 0.0,
    sources_data JSONB,
    claims_data JSONB,
    visuals_data JSONB,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    user_email TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Ensure user_id and user_email exist if table was already created
ALTER TABLE public.research_history ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.research_history ADD COLUMN IF NOT EXISTS user_email TEXT;

-- Index for fast history queries sorted by time
CREATE INDEX IF NOT EXISTS idx_research_history_created_at 
ON public.research_history (created_at DESC);

-- Index for fast user filtering
CREATE INDEX IF NOT EXISTS idx_research_history_user_id
ON public.research_history (user_id);

-- Enable Row Level Security (RLS)
ALTER TABLE public.research_history ENABLE ROW LEVEL SECURITY;

-- Allow public & authenticated read access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'research_history' AND policyname = 'Allow read access'
    ) THEN
        CREATE POLICY "Allow read access" ON public.research_history FOR SELECT USING (true);
    END IF;
END $$;

-- Allow public & authenticated insert access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'research_history' AND policyname = 'Allow insert access'
    ) THEN
        CREATE POLICY "Allow insert access" ON public.research_history FOR INSERT WITH CHECK (true);
    END IF;
END $$;
