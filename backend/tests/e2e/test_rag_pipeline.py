"""Step 2 acceptance: upload documents, then similarity-search in Arabic, French, English.

Requires: PostgreSQL + pgvector, BGE-M3 weights downloaded. OCR test additionally
requires TESSERACT_CMD / TESSDATA_PREFIX pointing at a Tesseract with ara+fra+eng.
"""

import io
import os

import pytest
from docx import Document as DocxDocument

from tests.e2e.conftest import make_company, search, upload_and_wait

POLICY_EN = """# Refund policy
Customers may request a full refund within 30 days of purchase. Refunds are issued
to the original payment method within 5 business days.

# Shipping policy
We ship worldwide. Standard delivery takes 5 to 7 business days and includes tracking.

# Privacy policy
We never sell customer data. Contact privacy@acme.example to request data deletion.
"""

POLICY_FR = """# Politique de remboursement
Les clients peuvent demander un remboursement complet dans les 30 jours suivant
l'achat. Le remboursement est effectue sous 5 jours ouvrables.

# Politique de livraison
Nous livrons dans le monde entier. La livraison standard prend 5 a 7 jours ouvrables.
"""

POLICY_AR = """# سياسة الاسترجاع
يحق للعميل طلب استرجاع كامل المبلغ خلال ثلاثين يوما من تاريخ الشراء. يتم رد المبلغ
خلال خمسة أيام عمل إلى وسيلة الدفع الأصلية.

# سياسة الشحن
نشحن إلى جميع أنحاء العالم. يستغرق التوصيل العادي من خمسة إلى سبعة أيام عمل.
"""


async def test_english_upload_and_search(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-en.md", POLICY_EN.encode())
    hits = await search(live_rag, company["api_key"], "How long do I have to ask for a refund?")
    assert hits, "no hits"
    assert "refund" in hits[0]["content"].lower()
    assert hits[0]["heading"] == "Refund policy"


async def test_french_upload_and_search(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-fr.md", POLICY_FR.encode())
    hits = await search(live_rag, company["api_key"], "Quel est le delai de remboursement ?")
    assert hits
    assert "remboursement" in hits[0]["content"].lower()


async def test_arabic_upload_and_search(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-ar.md", POLICY_AR.encode())
    hits = await search(live_rag, company["api_key"], "كم يوما لدي لطلب استرجاع المبلغ؟")
    assert hits
    assert "استرجاع" in hits[0]["content"]


async def test_arabic_diacritics_and_variants_match(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-ar.md", POLICY_AR.encode())
    # Query with alef variants + diacritics that normalization must unify.
    hits = await search(live_rag, company["api_key"], "ما هي سیاسَةُ الإِسترجاع؟")
    assert hits
    assert "استرجاع" in hits[0]["content"]


async def test_cross_language_arabic_query_english_doc(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-en.md", POLICY_EN.encode())
    hits = await search(live_rag, company["api_key"], "هل يمكنني استرجاع المبلغ خلال شهر؟")
    assert hits
    assert "refund" in hits[0]["content"].lower()


async def test_cross_language_french_query_english_doc(live_rag):
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-en.md", POLICY_EN.encode())
    hits = await search(live_rag, company["api_key"], "Combien de temps pour la livraison ?")
    assert hits
    assert "ship" in hits[0]["content"].lower() or "delivery" in hits[0]["content"].lower()


async def test_trilingual_corpus_language_routing(live_rag):
    company = await make_company(live_rag)
    key = company["api_key"]
    await upload_and_wait(live_rag, key, "policy-en.md", POLICY_EN.encode())
    await upload_and_wait(live_rag, key, "policy-fr.md", POLICY_FR.encode())
    await upload_and_wait(live_rag, key, "policy-ar.md", POLICY_AR.encode())

    en = await search(live_rag, key, "Can I get my money back after purchase?")
    fr = await search(live_rag, key, "Comment obtenir un remboursement ?")
    ar = await search(live_rag, key, "كيف أسترد أموالي بعد الشراء؟")
    assert en[0]["filename"] == "policy-en.md"
    assert fr[0]["filename"] == "policy-fr.md"
    assert ar[0]["filename"] == "policy-ar.md"


async def test_arabic_docx_upload(live_rag):
    docx = DocxDocument()
    docx.add_heading("سياسة الاسترجاع", level=1)
    docx.add_paragraph("يحق للعميل طلب استرجاع المبلغ خلال ثلاثين يوما من الشراء.")
    buf = io.BytesIO()
    docx.save(buf)
    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "policy-ar.docx", buf.getvalue())
    hits = await search(live_rag, company["api_key"], "مدة الاسترجاع")
    assert hits
    assert "استرجاع" in hits[0]["content"]


@pytest.mark.skipif(
    not os.environ.get("TESSERACT_CMD"), reason="TESSERACT_CMD not set; OCR E2E skipped"
)
async def test_scanned_arabic_image_ocr(live_rag, tmp_path):
    import arabic_reshaper
    from bidi.algorithm import get_display
    from PIL import Image, ImageDraw, ImageFont

    logical = "سياسة الاسترجاع خلال ثلاثين يوما من تاريخ الشراء"
    visual = get_display(arabic_reshaper.reshape(logical))
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 44)
    image = Image.new("RGB", (1400, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 50), visual, font=font, fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")

    company = await make_company(live_rag)
    await upload_and_wait(live_rag, company["api_key"], "scan-ar.png", buf.getvalue())
    hits = await search(live_rag, company["api_key"], "كم مدة الاسترجاع؟")
    assert hits
    assert "استرجاع" in hits[0]["content"] or "الاسترجاع" in hits[0]["content"]