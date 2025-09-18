"""
Checkpoint Manager for SH-7 Category Processing
Handles progress state persistence and resume capabilities
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

class CheckpointManager:
    """Manages processing checkpoints and resume state"""
    
    def __init__(self, checkpoint_file: str = "sh7_processing_checkpoint.json"):
        """
        Initialize checkpoint manager
        
        Args:
            checkpoint_file: Path to checkpoint file
        """
        self.checkpoint_file = checkpoint_file
        self.state = self._load_checkpoint()
    
    def _load_checkpoint(self) -> Dict:
        """Load checkpoint state from file"""
        if not os.path.exists(self.checkpoint_file):
            return self._create_initial_state()
        
        try:
            with open(self.checkpoint_file, 'r') as f:
                state = json.load(f)
            
            # Validate state structure
            if not self._validate_state(state):
                print(f"⚠️  Invalid checkpoint file, creating new one")
                return self._create_initial_state()
            
            print(f"📋 Loaded checkpoint: {state['completed_subcategories']} of {state['total_subcategories']} completed")
            return state
            
        except Exception as e:
            print(f"❌ Error loading checkpoint: {str(e)}, creating new one")
            return self._create_initial_state()
    
    def _create_initial_state(self) -> Dict:
        """Create initial processing state"""
        return {
            'processing_id': f"sh7_{int(time.time())}",
            'started_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'status': 'not_started',  # not_started, in_progress, completed, failed
            'total_subcategories': 17,
            'completed_subcategories': 0,
            'failed_subcategories': 0,
            'current_subcategory': None,
            'completed_list': [],
            'failed_list': [],
            'subcategory_results': {},
            'overall_stats': {
                'total_skus_collected': 0,
                'total_products_processed': 0,
                'total_processing_time': 0
            }
        }
    
    def _validate_state(self, state: Dict) -> bool:
        """Validate checkpoint state structure"""
        required_keys = [
            'processing_id', 'status', 'total_subcategories', 
            'completed_subcategories', 'completed_list', 'subcategory_results'
        ]
        
        return all(key in state for key in required_keys)
    
    def save_checkpoint(self):
        """Save current state to checkpoint file"""
        try:
            self.state['last_updated'] = datetime.now().isoformat()
            
            with open(self.checkpoint_file, 'w') as f:
                json.dump(self.state, f, indent=2, default=str)
            
        except Exception as e:
            print(f"❌ Error saving checkpoint: {str(e)}")
    
    def start_processing(self):
        """Mark processing as started"""
        self.state['status'] = 'in_progress'
        self.state['started_at'] = datetime.now().isoformat()
        self.save_checkpoint()
    
    def complete_subcategory(self, subcategory_code: str, result: Dict):
        """Mark a subcategory as completed"""
        if subcategory_code not in self.state['completed_list']:
            self.state['completed_list'].append(subcategory_code)
            self.state['completed_subcategories'] += 1
        
        self.state['subcategory_results'][subcategory_code] = result
        self.state['current_subcategory'] = None
        
        # Update overall stats
        if result.get('success', False):
            self.state['overall_stats']['total_skus_collected'] += result.get('skus_collected', 0)
            self.state['overall_stats']['total_products_processed'] += result.get('products_processed', 0)
        
        self.save_checkpoint()
    
    def fail_subcategory(self, subcategory_code: str, error: str):
        """Mark a subcategory as failed"""
        if subcategory_code not in self.state['failed_list']:
            self.state['failed_list'].append(subcategory_code)
            self.state['failed_subcategories'] += 1
        
        self.state['subcategory_results'][subcategory_code] = {
            'subcategory': subcategory_code,
            'success': False,
            'error': error,
            'skus_collected': 0,
            'products_processed': 0,
            'processing_time': 0
        }
        
        self.save_checkpoint()
    
    def set_current_subcategory(self, subcategory_code: str):
        """Set currently processing subcategory"""
        self.state['current_subcategory'] = subcategory_code
        self.save_checkpoint()
    
    def complete_processing(self):
        """Mark overall processing as completed"""
        self.state['status'] = 'completed'
        self.state['completed_at'] = datetime.now().isoformat()
        self.save_checkpoint()
    
    def fail_processing(self, error: str):
        """Mark overall processing as failed"""
        self.state['status'] = 'failed'
        self.state['error'] = error
        self.state['failed_at'] = datetime.now().isoformat()
        self.save_checkpoint()
    
    def is_subcategory_completed(self, subcategory_code: str) -> bool:
        """Check if subcategory is already completed"""
        return subcategory_code in self.state['completed_list']
    
    def is_subcategory_failed(self, subcategory_code: str) -> bool:
        """Check if subcategory has failed"""
        return subcategory_code in self.state['failed_list']
    
    def get_remaining_subcategories(self, all_subcategories: List[str]) -> List[str]:
        """Get list of subcategories that still need processing"""
        return [
            sub for sub in all_subcategories 
            if not self.is_subcategory_completed(sub) and not self.is_subcategory_failed(sub)
        ]
    
    def get_progress_summary(self) -> str:
        """Get formatted progress summary"""
        total = self.state['total_subcategories']
        completed = self.state['completed_subcategories']
        failed = self.state['failed_subcategories']
        remaining = total - completed - failed
        
        lines = [
            f"SH-7 Processing Progress",
            f"{'='*30}",
            f"Status: {self.state['status'].replace('_', ' ').title()}",
            f"Total subcategories: {total}",
            f"✅ Completed: {completed}",
            f"❌ Failed: {failed}",
            f"⏳ Remaining: {remaining}",
            f"📊 Products processed: {self.state['overall_stats']['total_products_processed']}",
            f"🔍 SKUs collected: {self.state['overall_stats']['total_skus_collected']}",
        ]
        
        if self.state.get('current_subcategory'):
            lines.append(f"🔄 Currently processing: {self.state['current_subcategory']}")
        
        return "\n".join(lines)
    
    def get_detailed_results(self) -> Dict:
        """Get detailed results for all processed subcategories"""
        return self.state['subcategory_results']
    
    def reset_checkpoint(self):
        """Reset checkpoint to initial state (use with caution)"""
        self.state = self._create_initial_state()
        self.save_checkpoint()
        print("🔄 Checkpoint reset to initial state")
    
    def cleanup_checkpoint(self):
        """Remove checkpoint file after successful completion"""
        try:
            if os.path.exists(self.checkpoint_file):
                os.remove(self.checkpoint_file)
                print(f"🗑️  Checkpoint file removed: {self.checkpoint_file}")
        except Exception as e:
            print(f"⚠️  Could not remove checkpoint file: {str(e)}")


def main():
    """Test checkpoint manager functionality"""
    checkpoint = CheckpointManager("test_checkpoint.json")
    
    print("Testing checkpoint manager...")
    print(checkpoint.get_progress_summary())
    
    # Simulate processing
    checkpoint.start_processing()
    checkpoint.set_current_subcategory("SH-7-2-28")
    checkpoint.complete_subcategory("SH-7-2-28", {
        'subcategory': 'SH-7-2-28',
        'success': True,
        'skus_collected': 4,
        'products_processed': 4,
        'processing_time': 15.5
    })
    
    print("\nAfter completing one subcategory:")
    print(checkpoint.get_progress_summary())
    
    # Cleanup test file
    os.remove("test_checkpoint.json")
    print("\nTest completed")


if __name__ == "__main__":
    main()