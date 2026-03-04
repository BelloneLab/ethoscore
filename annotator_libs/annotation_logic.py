import os
import pandas as pd
import numpy as np
from PySide6.QtWidgets import QMessageBox, QStatusBar


def load_annotations_from_csv(video_path, behaviors, parent=None):
    """Load annotations from CSV file if it exists using optimized NumPy access"""
    csv_path = os.path.splitext(video_path)[0] + '.csv'
    annotations = {}  # frame_number -> list of behaviors

    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            behaviors_in_csv = df.columns.tolist()[1:]

            # Check for behavior mismatches
            template_behaviors = set(behaviors)
            csv_behaviors = set(behaviors_in_csv)

            new_in_template = template_behaviors - csv_behaviors
            missing_in_template = csv_behaviors - template_behaviors

            if new_in_template or missing_in_template:
                # Sync the CSV file with template behaviors
                synced_df = sync_video_csv_with_template(df, behaviors, csv_path, parent)
                if synced_df is not None:
                    df = synced_df
                    behaviors_in_csv = df.columns.tolist()[1:]
                    df.to_csv(csv_path, index=False)
                else:
                    # User chose not to sync, return empty annotations
                    return annotations

            # Optimized loading using NumPy
            # Filter columns to only those in behaviors
            valid_cols = [b for b in behaviors_in_csv if b in behaviors]
            if not valid_cols:
                return annotations

            # Get frame numbers and behavior data as NumPy arrays
            frames = (df['Frames'].values - 1).astype(int)
            data = df[valid_cols].values

            # Find where labels are present (1s)
            rows, cols = np.where(data == 1)
            
            # Map column indices back to behavior names
            for row_idx, col_idx in zip(rows, cols):
                frame = frames[row_idx]
                behavior = valid_cols[col_idx]
                
                if frame not in annotations:
                    annotations[frame] = []
                annotations[frame].append(behavior)

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(parent, "Error", f"Could not load annotations: {str(e)}")

    return annotations


def sync_video_csv_with_template(df, template_behaviors, csv_path, parent=None):
    """Sync video CSV with template behaviors by adding/removing columns and handling mismatches"""
    behaviors_in_csv = df.columns.tolist()[1:]  # Skip 'Frames' column
    template_behaviors_set = set(template_behaviors)
    csv_behaviors_set = set(behaviors_in_csv)

    new_in_template = template_behaviors_set - csv_behaviors_set
    missing_in_template = csv_behaviors_set - template_behaviors_set

    # Notify about mismatches
    messages = []
    if new_in_template:
        messages.append(f"New behaviors in template: {', '.join(sorted(new_in_template))}")
    if missing_in_template:
        messages.append(f"Behaviors in video CSV not in template: {', '.join(sorted(missing_in_template))}")

    if messages:
        message = "Behavior mismatch detected:\n\n" + "\n".join(messages) + "\n\n"
        message += "New behaviors will be added as columns with all 0s.\n"
        if missing_in_template:
            message += "For behaviors missing from template, choose:\n"
            message += "- Hide: Don't display these behaviors\n"
            message += "- Delete: Remove entire rows with these behaviors"

            msg_box = QMessageBox(parent)
            msg_box.setWindowTitle("Behavior Mismatch")
            msg_box.setText(message)
            msg_box.setStandardButtons(QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes)
            hide_button = msg_box.button(QMessageBox.StandardButton.Yes)
            hide_button.setText("Hide")
            delete_button = msg_box.button(QMessageBox.StandardButton.No)
            delete_button.setText("Delete")
            msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = msg_box.exec()
            hide_missing = (reply == QMessageBox.StandardButton.Yes)
        else:
            QMessageBox.information(parent, "Behavior Mismatch", message + "Proceeding with sync.")
            hide_missing = False
    else:
        return df 

    # Create new dataframe with template behaviors
    synced_data = {'Frames': df['Frames'].copy()}

    # Add existing behaviors that are in template
    for behavior in template_behaviors:
        if behavior in df.columns:
            synced_data[behavior] = df[behavior].copy()
        else:
            # New behavior, add column with 0s
            synced_data[behavior] = [0] * len(df)

    synced_df = pd.DataFrame(synced_data)

    # Handle missing behaviors
    if missing_in_template and not hide_missing:
        # Optimized row deletion using NumPy
        mask = (df[list(missing_in_template)] == 1).any(axis=1)
        synced_df = synced_df[~mask.values].reset_index(drop=True)

    # Save the synced CSV
    csv_path = df.attrs.get('filename', 'synced.csv') if hasattr(df, 'attrs') else 'synced.csv'
    # Actually, the original path is not needed, just returning the df and let the caller save it manually

    return synced_df


def save_annotations_to_csv(video_path, annotations, behaviors, status_bar=None):
    """Save annotations to CSV file using optimized NumPy operations"""
    if not video_path:
        if status_bar:
            status_bar.showMessage("Error: No video loaded. Cannot save annotations.", 3000)
        else:
            print("Error: No video loaded. Cannot save annotations.")
        return

    csv_path = os.path.splitext(video_path)[0] + '.csv'
    total_frames = get_total_frames_from_video(video_path)
    if total_frames == 0:
        return

    # Use NumPy for fast data preparation
    num_behaviors = len(behaviors)
    behavior_to_idx = {b: i for i, b in enumerate(behaviors)}
    
    # Create zeroed array
    arr = np.zeros((total_frames, num_behaviors), dtype=np.int8)
    
    # Fill array from annotations dict
    for frame, active_list in annotations.items():
        if frame < total_frames:
            if isinstance(active_list, list):
                for b in active_list:
                    if b in behavior_to_idx:
                        arr[frame, behavior_to_idx[b]] = 1
            elif active_list in behavior_to_idx:
                arr[frame, behavior_to_idx[active_list]] = 1
    
    # Create DataFrame
    data = {'Frames': np.arange(1, total_frames + 1)}
    for i, b in enumerate(behaviors):
        data[b] = arr[:, i]

    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    
    if status_bar:
        status_bar.showMessage(f"Annotations saved to {csv_path}", 2000)
    else:
        print(f"Annotations saved to {csv_path}")


def get_total_frames_from_video(video_path):
    """Get total frames from video file"""
    import cv2
    cap = cv2.VideoCapture(video_path)
    if cap.isOpened():
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return total_frames
    return 0





def get_default_behaviors():
    """Get default behaviors list"""
    return ["nose-to-nose", "nose-to-body", "anogenital", "passive", "rearing", "fighting"]


def update_annotations_on_frame_change(annotations, current_frame, video_player, available_behaviors):
    """Update annotations when frame changes, handling active labels and removing mode"""

    # Check for range labeling preview - show behavior on current frame if within active range
    preview_behaviors = []
    for behavior, is_active in video_player.range_labeling_active.items():
        if is_active:
            start_frame = video_player.range_labeling_start.get(behavior)
            if start_frame is not None:
                # Show preview from start_frame to current_frame (inclusive)
                min_frame = min(start_frame, current_frame)
                max_frame = max(start_frame, current_frame)
                if min_frame <= current_frame <= max_frame:
                    preview_behaviors.append(behavior)

    # If in removing mode, remove labels from this frame
    if video_player.removing_mode:
        if current_frame in annotations:
            del annotations[current_frame]

    # Preview takes precedence over actual annotation
    if preview_behaviors:
        # Show preview behaviors
        active_behaviors_list = preview_behaviors
    else:
        # Show actual annotation
        current_behavior = annotations.get(current_frame, [])
        if isinstance(current_behavior, list):
            active_behaviors_list = current_behavior
        elif current_behavior:
            active_behaviors_list = [current_behavior]
        else:
            active_behaviors_list = []

    video_player.current_behavior = active_behaviors_list

    return active_behaviors_list


def handle_label_state_change(annotations, behavior, is_active, current_frame, video_player):
    """Handle label state change for a behavior"""
    if is_active:
        if video_player.multitrack_enabled:
            # Get current behaviors for this frame
            current_behaviors = annotations.get(current_frame, [])
            
            # Ensure it's a list
            if not isinstance(current_behaviors, list):
                current_behaviors = [current_behaviors] if current_behaviors else []
            
            # Add behavior if not already present
            if behavior not in current_behaviors:
                current_behaviors.append(behavior)
            
            annotations[current_frame] = current_behaviors
        else:
            # Multitrack disabled: set to a list with only the new behavior
            annotations[current_frame] = [behavior]
    else:
        # Deactivating behavior
        if current_frame in annotations:
            current_behaviors = annotations[current_frame]
            if isinstance(current_behaviors, list):
                if behavior in current_behaviors:
                    current_behaviors.remove(behavior)
                if not current_behaviors:
                    del annotations[current_frame]
            elif current_behaviors == behavior:
                del annotations[current_frame]

    # Update display
    current_behavior = annotations.get(current_frame, [])
    if not isinstance(current_behavior, list):
        current_behavior = [current_behavior] if current_behavior else []
    
    video_player.current_behavior = current_behavior
    video_player.update_frame_display()

    return current_behavior


def remove_labels_from_frame(annotations, current_frame, video_player):
    """Remove label from the current frame"""
    if current_frame in annotations:
        del annotations[current_frame]

    # Clear active labels
    video_player.active_labels = {}
    video_player.is_toggled_active = {}
    video_player.is_stopping_toggle = {}

    # Update display
    video_player.current_behavior = []
    return []


def check_label_removal_on_backward_navigation(annotations, target_frame, video_player, available_behaviors):
    """Check if labels should be removed from subsequent frames when moving backwards"""
    removed_labels = []
    for behavior in available_behaviors:
        held = video_player.label_key_held.get(behavior, False)
        active = video_player.active_labels.get(behavior, False)
        
        # Check if behavior is present in target frame
        is_in_target = False
        if target_frame in annotations:
            if isinstance(annotations[target_frame], list):
                is_in_target = behavior in annotations[target_frame]
            else:
                is_in_target = behavior == annotations[target_frame]

        if (held or active) and is_in_target:
            # Remove from all frames > target_frame
            for frame in list(annotations.keys()):
                if frame > target_frame:
                    if isinstance(annotations[frame], list):
                        if behavior in annotations[frame]:
                            annotations[frame].remove(behavior)
                            removed_labels.append((frame, behavior))
                            if not annotations[frame]:
                                del annotations[frame]
                    elif behavior == annotations[frame]:
                        del annotations[frame]
                        removed_labels.append((frame, behavior))
    return removed_labels


def handle_behavior_removal(annotations, behavior, available_behaviors):
    """Handle behavior removal - remove from annotations"""
    # Remove from annotations if present
    for frame in list(annotations.keys()):
        if isinstance(annotations[frame], list):
            if behavior in annotations[frame]:
                annotations[frame].remove(behavior)
                if not annotations[frame]:
                    del annotations[frame]
        elif behavior == annotations[frame]:
            del annotations[frame]


def apply_range_label(annotations, behavior, start_frame, end_frame, available_behaviors, include_last_frame=True, multitrack_enabled=True):
    """Apply a behavior label to a range of frames"""
    if behavior not in available_behaviors:
        return

    # Ensure start_frame <= end_frame
    if start_frame > end_frame:
        start_frame, end_frame = end_frame, start_frame

    # Determine the end frame based on the include_last_frame setting
    if include_last_frame:
        # Include the last frame (original behavior)
        range_end = end_frame + 1
    else:
        # Exclude the last frame
        range_end = end_frame

    # Apply the label to all frames in the range
    for frame in range(start_frame, range_end):
        if multitrack_enabled:
            # Get current behaviors for this frame
            current_behaviors = annotations.get(frame, [])
            
            # Ensure it's a list
            if not isinstance(current_behaviors, list):
                current_behaviors = [current_behaviors] if current_behaviors else []
            
            # Add behavior if not already present
            if behavior not in current_behaviors:
                current_behaviors.append(behavior)
            
            annotations[frame] = current_behaviors
        else:
            # Replace existing behaviors
            annotations[frame] = [behavior]


def remove_range_labels(annotations, start_frame, end_frame):
    """Remove labels from a range of frames (inclusive)"""
    # Ensure start_frame <= end_frame
    if start_frame > end_frame:
        start_frame, end_frame = end_frame, start_frame

    # Remove labels from all frames in the range
    for frame in range(start_frame, end_frame + 1):
        if frame in annotations:
            del annotations[frame]


def remove_behavior_from_range(annotations, behavior, start_frame, end_frame):
    """Remove a specific behavior from a range of frames"""
    if start_frame > end_frame:
        start_frame, end_frame = end_frame, start_frame

    for frame in range(start_frame, end_frame + 1):
        if frame in annotations:
            behaviors = annotations[frame]
            if isinstance(behaviors, list):
                if behavior in behaviors:
                    behaviors.remove(behavior)
                if not behaviors:
                    del annotations[frame]
                else:
                    annotations[frame] = behaviors
            elif behaviors == behavior:
                del annotations[frame]


def change_label_type_in_range(annotations, old_behavior, new_behavior, start_frame, end_frame):
    """Change label type for a range of frames"""
    if start_frame > end_frame:
        start_frame, end_frame = end_frame, start_frame

    for frame in range(start_frame, end_frame + 1):
        if frame in annotations:
            behaviors = annotations[frame]
            if isinstance(behaviors, list):
                if old_behavior in behaviors:
                    behaviors.remove(old_behavior)
                if new_behavior not in behaviors:
                    behaviors.append(new_behavior)
                if not behaviors:
                    del annotations[frame]
                else:
                    annotations[frame] = behaviors
            elif behaviors == old_behavior:
                annotations[frame] = [new_behavior]
        else:
            # If no behavior was present, but we are changing to new_behavior, 
            # should we add it? The logic usually implies changing an existing label.
            # For now, let's only change if something was there.
            pass


def handle_range_label_state_change(annotations, behavior, start_frame, end_frame, current_frame, video_player):
    """Handle range-based label state change - apply label to range and update UI"""
    # Apply the label to the range
    apply_range_label(annotations, behavior, start_frame, end_frame, video_player.available_behaviors, 
                      video_player.include_last_frame_in_range, video_player.multitrack_enabled)

    # Update current behavior for display (based on current frame)
    current_behavior = annotations.get(current_frame, [])
    if not isinstance(current_behavior, list):
        current_behavior = [current_behavior] if current_behavior else []
    
    video_player.current_behavior = current_behavior
    video_player.update_frame_display()

    return current_behavior
