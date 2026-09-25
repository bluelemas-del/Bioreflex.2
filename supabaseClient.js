import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseAnonKey = process.env.SUPABASE_ANON_KEY;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// Fetching data
async function getData() {
  const { data, error } = await supabase
    .from('bioreflex_data')
    .select('*');
    
  if (error) console.error('Error fetching data:', error);
  else console.log('Data:', data);
}

// Inserting data
async function addSample(sampleName, value) {
  const { data, error } = await supabase
    .from('bioreflex_data')
    .insert([{ sample_name: sampleName, metric_value: value }]);
}