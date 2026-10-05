from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from agent.embeddings import embed_texts
from papers.models import Chunk, Paper
from workspaces.models import Workspace

PASSAGES = [
    "The Transformer relies entirely on self-attention to compute representations of its input and output without using sequence-aligned recurrent networks or convolution.",
    "Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions.",
    "Self-attention connects all positions with a constant number of sequentially executed operations, whereas a recurrent layer requires O(n) sequential operations.",
    "The model was trained on the WMT 2014 English-to-German dataset of about 4.5 million sentence pairs, using byte-pair encoding.",
]


# creates a known user, workspace and ready paper for demos and the e2e test
class Command(BaseCommand):
    help = "Seed a demo user, workspace and ready paper (only with DEBUG or LLM_PROVIDER=demo)"

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo-pass-12345")

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.LLM_PROVIDER == "demo"):
            raise CommandError("seed_demo creates a user with a known password; refusing outside dev/demo mode")

        user, _ = User.objects.get_or_create(username="demo")
        user.set_password(options["password"])
        user.save()
        workspace, _ = Workspace.objects.get_or_create(user=user, name="Transformers")
        paper, _ = Paper.objects.get_or_create(
            workspace=workspace,
            arxiv_id="1706.03762",
            defaults={
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani", "Noam Shazeer"],
                "pdf_url": "https://arxiv.org/pdf/1706.03762",
            },
        )
        Chunk.objects.filter(paper=paper).delete()
        embeddings = embed_texts(PASSAGES)
        Chunk.objects.bulk_create(
            Chunk(paper=paper, chunk_index=i, text=text, token_count=len(text.split()), embedding=vector)
            for i, (text, vector) in enumerate(zip(PASSAGES, embeddings))
        )
        paper.status = "ready"
        paper.save(update_fields=["status"])
        self.stdout.write(self.style.SUCCESS(f"Seeded user 'demo' with workspace '{workspace.name}'"))
