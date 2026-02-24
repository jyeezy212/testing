#!/usr/bin/env python3
"""
Local testing script - simulates ChatGPT Custom GPT behavior
Run this to test before uploading to ChatGPT
"""

from pathlib import Path
import sys

# Windows terminals default to cp1252 which can't print emoji — force UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from artwork_checker_v2_1_xlsx import ArtworkChecker

def main():
    print("=" * 60)
    print("LOCAL TEST - Simulating ChatGPT Custom GPT")
    print("=" * 60)
    
    # Your test files (same ones you upload to ChatGPT)
    copy_doc = Path("test_files/5_Body_Butter_250ml_-_Carton.xlsx")
    artwork = Path("test_files/5__Amika_Body_BodyButter_Carton_AW_090225_VC_22640.pdf")
    
    # Validate files exist
    if not copy_doc.exists():
        print(f"❌ ERROR: Copy document not found: {copy_doc}")
        print(f"   Current directory: {Path.cwd()}")
        return
    
    if not artwork.exists():
        print(f"❌ ERROR: Artwork not found: {artwork}")
        print(f"   Current directory: {Path.cwd()}")
        return
    
    print(f"✅ Copy document found: {copy_doc.name}")
    print(f"✅ Artwork found: {artwork.name}")
    print()
    
    try:
        # Run the checker (exactly like ChatGPT does)
        checker = ArtworkChecker()
        report = checker.run_check(
            copy_path=copy_doc,
            artwork_paths=[artwork],
            output_dir=Path("output"),
        )
        
        print("\n" + "=" * 60)
        print("✅ SUCCESS! Check completed without errors")
        print("=" * 60)
        print(f"\nReport saved to: output/artwork_check_report.md")
        print(f"Report length: {len(report):,} characters")
        
        # Show first 500 chars of report
        print("\n--- Report Preview ---")
        print(report[:500])
        print("...\n")
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ ERROR OCCURRED")
        print("=" * 60)
        print(f"\nError type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        print("\n--- Full Traceback ---")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()