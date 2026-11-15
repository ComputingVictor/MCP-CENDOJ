import os
import shutil
import pytest
import asyncio
import sqlite3
import time
from app.scraper import CendojScraper
from app.mcp_server import descargar_pdf_resolucion, exportar_resolucion_markdown

# We will run a real search for testing
TEST_QUERY = "contrato de arrendamiento"

def run_async(coro):
    return asyncio.run(coro)

def test_scraper_search():
    async def run():
        async with CendojScraper(headless=True) as scraper:
            response = await scraper.search(query=TEST_QUERY, page_num=1)
            assert response.total > 0
            assert len(response.results) > 0
            first = response.results[0]
            assert first.id is not None
            assert first.url_pdf.startswith("http")
            return first
            
    first_result = run_async(run())
    pytest.shared_result = first_result  # save for subsequent tests
    pytest.shared_page1_ecli = first_result.ecli

def test_scraper_pagination():
    # Regression: pagination used to click a hidden anchor and always time out.
    async def run():
        async with CendojScraper(headless=True) as scraper:
            response = await scraper.search(query=TEST_QUERY, page_num=2)
            assert response.total > 0
            assert len(response.results) > 0
            return response.results[0]

    page2_first = run_async(run())
    assert page2_first.url_pdf.startswith("http")
    if getattr(pytest, "shared_page1_ecli", None) and page2_first.ecli:
        assert page2_first.ecli != pytest.shared_page1_ecli, "page 2 returned the same first result as page 1"

def test_scraper_pdf_download_and_cache():
    # Make sure search test ran first
    if not hasattr(pytest, "shared_result"):
        pytest.skip("requires a successful search (test_scraper_search)")
    first = pytest.shared_result
    
    async def run():
        async with CendojScraper(headless=True) as scraper:
            # First download - should hit the web and write to cache
            start = time.time()
            text_1 = await scraper.download_pdf_text(first.url_pdf)
            time_1 = time.time() - start
            
            assert len(text_1) > 0
            
            # Verify it exists in SQLite database cache
            assert scraper.cache_db is not None
            assert os.path.exists(scraper.cache_db)
            
            conn = sqlite3.connect(scraper.cache_db)
            cursor = conn.cursor()
            cursor.execute("SELECT text FROM pdf_text_cache WHERE pdf_url = ?", (first.url_pdf,))
            row = cursor.fetchone()
            conn.close()
            assert row is not None
            assert len(row[0]) == len(text_1)
            
            # Second download - should hit cache instantly
            start = time.time()
            text_2 = await scraper.download_pdf_text(first.url_pdf)
            time_2 = time.time() - start
            
            assert text_1 == text_2
            # Cache hit should be much faster
            assert time_2 < time_1
            assert time_2 < 0.5
            
    run_async(run())

def test_descargar_pdf_resolucion():
    if not hasattr(pytest, "shared_result"):
        pytest.skip("requires a successful search (test_scraper_search)")
    first = pytest.shared_result
    
    async def run():
        result_msg = await descargar_pdf_resolucion(first.url_pdf, filename="test_down.pdf")
        assert "PDF descargado y guardado correctamente" in result_msg
        
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        downloads_dir = os.path.join(project_dir, "downloads")
        dest_path = os.path.join(downloads_dir, "test_down.pdf")
        
        assert os.path.exists(dest_path)
        assert os.path.getsize(dest_path) > 100
        
        # Clean up
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
    run_async(run())

def test_exportar_resolucion_markdown():
    if not hasattr(pytest, "shared_result"):
        pytest.skip("requires a successful search (test_scraper_search)")
    first = pytest.shared_result
    
    async def run():
        result_msg = await exportar_resolucion_markdown(
            pdf_url=first.url_pdf,
            titulo=first.titulo,
            fecha=first.fecha,
            organo=first.organo,
            sede=first.sede,
            ponente=first.ponente,
            roj=first.roj,
            ecli=first.ecli,
            n_recurso=first.n_recurso,
            n_resolucion=first.n_resolucion,
            filename="test_export.md"
        )
        assert "Resolución exportada exitosamente a Markdown" in result_msg
        
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exports_dir = os.path.join(project_dir, "exports")
        dest_path = os.path.join(exports_dir, "test_export.md")
        
        assert os.path.exists(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        assert f"Resolución Judicial: {first.titulo}" in content
        assert f"**ROJ**: {first.roj}" in content
        assert "Texto Completo de la Resolución" in content
        
        # Clean up
        if os.path.exists(dest_path):
            os.remove(dest_path)
            
    run_async(run())
