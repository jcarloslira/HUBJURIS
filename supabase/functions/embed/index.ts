// Edge Function `embed` — gera embeddings com o modelo gte-small (384 dims)
// rodando no próprio Supabase (sem custo). Usada pela base de conhecimento (RAG).
// Aceita { input: string } ou { input: string[] } e devolve { embeddings: number[][] }.
//
// Deploy: via Supabase MCP/CLI. Chamada pelo backend em app/services/conhecimento.py.
const session = new Supabase.ai.Session('gte-small');

Deno.serve(async (req) => {
  try {
    const { input } = await req.json();
    if (input === undefined || input === null) {
      return new Response(JSON.stringify({ error: 'campo "input" ausente' }), {
        status: 400, headers: { 'Content-Type': 'application/json' },
      });
    }
    const inputs = Array.isArray(input) ? input : [input];
    const embeddings: number[][] = [];
    for (const texto of inputs) {
      const emb = await session.run(String(texto), { mean_pool: true, normalize: true });
      embeddings.push(emb as number[]);
    }
    return new Response(JSON.stringify({ embeddings }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500, headers: { 'Content-Type': 'application/json' },
    });
  }
});
