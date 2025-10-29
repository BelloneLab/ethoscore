import os
import pandas as pd
from PySide6.QtWidgets import QMessageBox, QStatusBar # Import QStatusBar


def load_annotations_from_csv(video_path, behaviors, parent=None):
    """Load annotations from CSV file if it exists"""
    csv_path = os.path.splitext(video_path)[0] + '.csv'
    annotations = {}  # frame_number -> behavior (single)

    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            behaviors_in_csv = df.columns.tolist()[1:]  # Skip 'Frames' column

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
                    # Save the synced CSV
                    df.to_csv(csv_path, index=False)
                else:
                    # User chose not to sync, return empty annotations
                    return annotations

            # Load annotations - take the first behavior that is 1
            for idx, row in df.iterrows():
                frame = int(row['Frames']) - 1  # 0-based
                for b in behaviors_in_csv:
                    if b in behaviors and row[b] == 1:  # Only include behaviors that are in template
                        annotations[frame] = b
                        break  # Only take the first one

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

    # Notify user about mismatches
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
        return df  # No changes needed

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
    # Actually, we need to save it back to the original path
    # But since we don't have the path here, we'll return the dataframe and let the caller save it

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
        active = annotations.get(frame, None)
        for b in behaviors:
            data[b].append(1 if b == active else 0)

    df = pd.DataFrame(data)
    df.to_csv(csv_path, index=False)
    if status_bar:
        status_bar.showMessage(f"Annotations saved to {csv_path}", 2000) # Show message for 2 seconds
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


def load_behaviors_from_csv(behaviors_file="behaviors.csv", parent=None):
    """Load behaviors from behaviors.csv if available"""
    if os.path.exists(behaviors_file):
        try:
            with open(behaviors_file, 'r') as f:
                line = f.readline().strip()
                behaviors = [b.strip() for b in line.split(',') if b.strip()]
        except Exception as e:
            QMessageBox.warning(parent, "Error", f"Could not load behaviors.csv: {str(e)}")
            behaviors = get_default_behaviors()
    else:
        # Show popup to create behaviors.csv
        reply = QMessageBox.question(parent, "Create Behavior Template",
                                   "No behavior.csv file found. Would you like to create one with default behaviors?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            behaviors = get_default_behaviors()
            save_behaviors_to_csv(behaviors)
        else:
            behaviors = []

    return behaviors


def save_behaviors_to_csv(behaviors, behaviors_file="behaviors.csv"):
    """Save behaviors list to behaviors.csv"""
    try:
        with open(behaviors_file, 'w') as f:
            f.write(','.join(behaviors))
    except Exception as e:
        QMessageBox.warning(None, "Error", f"Could not save behaviors.csv: {str(e)}")


def get_default_behaviors():
    """Get default behaviors list"""
    return ["nose-to-nose", "nose-to-body", "anogenital", "passive", "rearing", "fighting"]


def update_annotations_on_frame_change(annotations, current_frame, video_player, available_behaviors):
    """Update annotations when frame changes, handling active labels and removing mode"""

    # If in removing mode, remove labels from this frame
    if video_player.removing_mode:
        if current_frame in annotations:
            del annotations[current_frame]

    # Handle hold mode: if a behavior is being held, apply it to the current frame
    if hasattr(video_player, 'held_behavior') and video_player.held_behavior:
        behavior = video_player.held_behavior
        annotations[current_frame] = behavior

    # If there are active labels (from continuous labeling), apply them to this frame
    active_behaviors = [b for b, active in video_player.active_labels.items() if active]
    if active_behaviors:
        # Only one behavior can be active at a time, take the first one
        behavior = active_behaviors[0]
        if not (video_player.label_key_held.get(behavior, False) and current_frame in annotations and behavior == annotations[current_frame]):
            annotations[current_frame] = behavior

    # Update current behavior for display
    current_behavior = annotations.get(current_frame, None)
    active_behaviors_list = [current_behavior] if current_behavior else []
    video_player.current_behavior = active_behaviors_list

    return active_behaviors_list


def handle_label_state_change(annotations, behavior, is_active, current_frame, video_player):
    """Handle label state change for a behavior"""
    if is_active:
        # Set this behavior for the frame (replaces any existing)
        annotations[current_frame] = behavior
    else:
        # Remove the label from this frame if it matches
        if current_frame in annotations and annotations[current_frame] == behavior:
            del annotations[current_frame]

    # Update display
    current_behavior = annotations.get(current_frame, None)
    active_behaviors_list = [current_behavior] if current_behavior else []
    video_player.current_behavior = active_behaviors_list
    video_player.update_frame_display()

    return active_behaviors_list


def remove_labels_from_frame(annotations, current_frame, video_player):
    """Remove label from the current frame"""
    if current_frame in annotations:
        del annotations[current_frame]

    # Clear active labels
    video_player.active_labels = {}
    video_player.is_toggled_active = {}
    video_player.is_stopping_toggle = {}

    # Update display
    current_behavior = annotations.get(current_frame, None)
    active_behaviors_list = [current_behavior] if current_behavior else []
    return active_behaviors_list


def check_label_removal_on_backward_navigation(annotations, target_frame, video_player, available_behaviors):
    """Check if labels should be removed from subsequent frames when moving backwards"""
    for behavior in available_behaviors:
        held = video_player.label_key_held.get(behavior, False)
        active = video_player.active_labels.get(behavior, False)
        if (held or active) and target_frame in annotations and behavior == annotations[target_frame]:
            # Remove from all frames > target_frame
            for frame in list(annotations.keys()):
                if frame > target_frame and behavior == annotations[frame]:
                    del annotations[frame]


def handle_behavior_removal(annotations, behavior, available_behaviors):
    """Handle behavior removal - remove from annotations"""
    # Remove from annotations if present
    for frame in list(annotations.keys()):
        if behavior == annotations[frame]:
            del annotations[frame]
