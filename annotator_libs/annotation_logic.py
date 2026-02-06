import os
import pandas as pd
from PySide6.QtWidgets import QMessageBox, QStatusBar


def load_annotations_from_csv(video_path, behaviors, parent=None):
    """Load annotations from CSV file if it exists"""
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

            # Load annotations
            for idx, row in df.iterrows():
                frame = int(row['Frames']) - 1  # 0-based
                frame_behaviors = []
                for b in behaviors_in_csv:
                    if b in behaviors and row[b] == 1: 
                        frame_behaviors.append(b)
                if frame_behaviors:
                    annotations[frame] = frame_behaviors

        except Exception as e:
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
        # Delete rows that have missing behaviors set to 1
        rows_to_keep = []
        for idx, row in df.iterrows():
            keep_row = True
            for missing_behavior in missing_in_template:
                if row[missing_behavior] == 1:
                    keep_row = False
                    break
            if keep_row:
                rows_to_keep.append(idx)

        if rows_to_keep:
            synced_df = synced_df.loc[rows_to_keep].reset_index(drop=True)
        else:
            QMessageBox.warning(parent, "Warning", "All rows would be deleted. Keeping original data.")
            return df

    # Save the synced CSV
    csv_path = df.attrs.get('filename', 'synced.csv') if hasattr(df, 'attrs') else 'synced.csv'
    # Actually, the original path is not needed, just returning the df and let the caller save it manually

    return synced_df


def save_annotations_to_csv(video_path, annotations, behaviors, status_bar=None):
    """Save annotations to CSV file in video2_2.csv format"""
    if not video_path:
        if status_bar:
            status_bar.showMessage("Error: No video loaded. Cannot save annotations.", 3000)
        else:
            print("Error: No video loaded. Cannot save annotations.")
        return

    csv_path = os.path.splitext(video_path)[0] + '.csv'

    # Create data dict
    data = {'Frames': list(range(1, get_total_frames_from_video(video_path) + 1))}
    for b in behaviors:
        data[b] = []

    total_frames = get_total_frames_from_video(video_path)
    for frame in range(total_frames):
        active_list = annotations.get(frame, [])
        for b in behaviors:
            # Handle both old (single string) and new (list) annotation formats
            if isinstance(active_list, list):
                data[b].append(1 if b in active_list else 0)
            else:
                data[b].append(1 if b == active_list else 0)

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
