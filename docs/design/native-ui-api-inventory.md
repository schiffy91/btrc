# Native UI: existing API qualification checklist

Status: inventory for review, 2026-09-21. Part of [PLAN.md](../../PLAN.md) and
[the native UI roadmap](native-ui-parity.md). Extracted from the current working
tree on btrc HEAD `4e5c98239868e805586524b4ee06424bf4556130`.

This lists **all 135 directly declared methods in 24 interfaces across 19
`GUI/I*.btrc` files**, plus **27 `GUI` factory/service methods**. The 162 entries
make the existing interface/facade portion of UI0 individually reviewable.
They are neither 162 independent behaviors nor proof of working providers.
Each operation ID is its declaring owner and method name. Preserve IDs across
compatible edits; record signature changes and split overloaded operations
explicitly if overloads are introduced.

The broader inventory remains **60 capability families / 300 platform cells**,
with **47 proposed behavioral cases / 470 provider–frontend result slots**.
Those cases exercise groups of operations. Do not add those counts to this
checklist or interpret either denominator as the complete public stdlib API.
Exported helper values, other GUI modules, `App`, `UI`, callback/resource owners,
and BTRSmith journeys still need their own operation mapping under UI0.

## How an entry becomes qualified

For each entry, UI0 records macOS, Linux, Windows, iOS/iPadOS and Android,
each through the reference and self-hosted frontend: **1,620 planned operation
mapping slots** for this initial surface. A shared fixture can cover several
entries, but must name its actual assertions. Getters, setters, factories and
inherited behavior need evidence at their concrete receivers; counting an
inherited declaration once does not exempt any control from testing it.

Every slot records implementation state separately from qualification state:
source owner/provider, exact signature, supported OS/toolkit configuration,
linked case/fixture/assertion, input mechanism, frontend/compiler revision,
result and evidence artifact. A missing provider remains missing even when its
runner is unavailable. Existing tests can supply evidence after their scope and
revision are checked; this source audit reran no native tests. No slot is
marked passed here.

Exercise normal use, invalid input, closed/detached/disabled receivers where
applicable, callback cancellation and partial failure. Preserve documented
ownership and executor requirements. Query operations must agree with visible
state; setters must preserve unchanged editing state and emit no user action;
factories must clean up partial construction. Native defaults need real input
or OS inspection evidence when they carry the behavior. An unsupported
operation needs a typed outcome or documented platform adaptation, plus a
usable product alternative; a silent no-op cannot satisfy parity.

The family, milestone and case references below route review to the existing
roadmap. They are **starting coverage links at owner level**, not a claim that
each listed E-case already covers every method. UI0 must resolve that mapping
per entry and add missing assertions before closing the milestone.

## IApplicationWork

Source: [IApplication.btrc](../../src/stdlib/GUI/IApplication.btrc). Families: N04.
Milestones: UI2. Starting cases: E04, E24, E30, E31, E40.

| Operation ID | Current declaration |
| --- | --- |
| `IApplicationWork.run` | `void run();` |

## IApplication

Source: [IApplication.btrc](../../src/stdlib/GUI/IApplication.btrc). Families: N01–N04.
Milestones: UI1/UI2. Starting cases: E04, E08, E16, E30, E31, E40, E46, E47.

| Operation ID | Current declaration |
| --- | --- |
| `IApplication.createWindow` | `IWindow createWindow(string title, double width, double height);` |
| `IApplication.post` | `void post(IApplicationWork work);` |
| `IApplication.postAfter` | `ICallbackRegistration postAfter(double delaySeconds, IApplicationWork work);` |
| `IApplication.isRunning` | `bool isRunning();` |
| `IApplication.run` | `void run();` |
| `IApplication.requestQuit` | `void requestQuit();` |
| `IApplication.close` | `CallbackCancellation close();` |
| `IApplication.pollClose` | `CallbackCancellation pollClose();` |

## IButtonAction

Source: [IButton.btrc](../../src/stdlib/GUI/IButton.btrc). Families: N05/N11.
Milestones: UI2/UI4. Starting cases: E06, E13, E23, E31, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IButtonAction.invoke` | `void invoke();` |

## IButton

Source: [IButton.btrc](../../src/stdlib/GUI/IButton.btrc). Extends `IView`. Families: N05/N11/N34.
Milestones: UI2/UI3/UI4/UI7. Starting cases: E06, E13, E15, E23, E31, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IButton.title` | `string title();` |
| `IButton.setTitle` | `void setTitle(string title);` |
| `IButton.isEnabled` | `bool isEnabled();` |
| `IButton.setEnabled` | `void setEnabled(bool enabled);` |
| `IButton.setFont` | `void setFont(double size);` |
| `IButton.setCentered` | `void setCentered(bool centered);` |
| `IButton.setSystemSymbol` | `void setSystemSymbol(string name);` |
| `IButton.setToolTip` | `void setToolTip(string text);` |
| `IButton.toolTip` | `string toolTip();` |
| `IButton.setSelected` | `void setSelected(bool selected);` |
| `IButton.isSelected` | `bool isSelected();` |
| `IButton.setTransparent` | `void setTransparent(bool transparent);` |
| `IButton.setBordered` | `void setBordered(bool bordered);` |
| `IButton.cancelPendingActions` | `void cancelPendingActions();` |
| `IButton.activate` | `bool activate();` |
| `IButton.onAction` | `ICallbackRegistration onAction(IButtonAction action, CallbackScope scope);` |

## IContainer

Source: [IContainer.btrc](../../src/stdlib/GUI/IContainer.btrc). Extends `IView`. Families: N03/N24.
Milestones: UI2/UI5. Starting cases: E29, E31, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IContainer.attach` | `void attach(IView child);` |
| `IContainer.detach` | `IView detach(IView child);` |
| `IContainer.childCount` | `int childCount();` |
| `IContainer.childAt` | `IView childAt(int index);` |

## IDirectoryPicker

Source: [IDirectoryPicker.btrc](../../src/stdlib/GUI/IDirectoryPicker.btrc). Families: N35/N36.
Milestones: UI7. Starting cases: E10, E17, E23.

| Operation ID | Current declaration |
| --- | --- |
| `IDirectoryPicker.chooseDirectory` | `DirectoryPickerOutcome chooseDirectory(DirectoryPickerRequest request);` |

## IGPUView

Source: [IGPUView.btrc](../../src/stdlib/GUI/IGPUView.btrc). Extends `IView`. Families: N47–N50.
Milestones: UI9/UI10. Starting cases: E11, E12, E27, E31, E32, E38, E42, E43.

| Operation ID | Current declaration |
| --- | --- |
| `IGPUView.poll` | `bool poll();` |
| `IGPUView.error` | `string error();` |
| `IGPUView.backingScale` | `double backingScale();` |
| `IGPUView.pixelWidth` | `int pixelWidth();` |
| `IGPUView.pixelHeight` | `int pixelHeight();` |
| `IGPUView.frameRenderer` | `GPUSurfaceRenderer frameRenderer();` |
| `IGPUView.beginFrame` | `GPUFrameAvailability beginFrame(double red, double green, double blue, double alpha = 1.0);` |
| `IGPUView.createProgram` | `GPUProgram createProgram(string source, int uniformFloatCount, bool textured = true, bool sourceOver = true, string vertexEntry = "vs_main", string fragmentEntry = "fs_main");` |
| `IGPUView.readback` | `GPUReadback readback(int maximumPixels = 16777216);` |
| `IGPUView.requestCapture` | `void requestCapture();` |

## IGrid

Source: [IGrid.btrc](../../src/stdlib/GUI/IGrid.btrc). Extends `IView`. Families: N23/N24.
Milestones: UI5. Starting cases: E15, E26, E29, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IGrid.columnCount` | `int columnCount();` |
| `IGrid.rowCount` | `int rowCount();` |
| `IGrid.setChild` | `void setChild(int column, int row, IView? child);` |
| `IGrid.childAt` | `IView? childAt(int column, int row);` |
| `IGrid.setSpacing` | `void setSpacing(double columnSpacing, double rowSpacing);` |
| `IGrid.setColumnWidth` | `void setColumnWidth(int column, double width);` |
| `IGrid.fitColumn` | `void fitColumn(int column);` |
| `IGrid.setRowHeight` | `void setRowHeight(int row, double height);` |
| `IGrid.fitRow` | `void fitRow(int row);` |
| `IGrid.setRowHidden` | `void setRowHidden(int row, bool hidden);` |
| `IGrid.setColumnHidden` | `void setColumnHidden(int column, bool hidden);` |
| `IGrid.layout` | `void layout();` |

## IImageHandle

Source: [IImageHandle.btrc](../../src/stdlib/GUI/IImageHandle.btrc). Families: N03/N20/N49.
Milestones: UI2/UI4/UI9. Starting cases: E24, E31, E35, E36.

| Operation ID | Current declaration |
| --- | --- |
| `IImageHandle.width` | `int width();` |
| `IImageHandle.height` | `int height();` |
| `IImageHandle.isOpen` | `bool isOpen();` |
| `IImageHandle.close` | `void close();` |

## IImageView

Source: [IImageView.btrc](../../src/stdlib/GUI/IImageView.btrc). Extends `IView`. Families: N20/N49.
Milestones: UI4/UI9. Starting cases: E20, E24, E35, E36.

| Operation ID | Current declaration |
| --- | --- |
| `IImageView.setImage` | `void setImage(Image? pixels, int maximumPixels = 16777216);` |
| `IImageView.setImageHandle` | `void setImageHandle(IImageHandle? handle);` |

## ILabel

Source: [ILabel.btrc](../../src/stdlib/GUI/ILabel.btrc). Extends `IView`. Families: N14/N44/N45.
Milestones: UI4/UI5/UI8. Starting cases: E15, E20, E26, E28, E37.

| Operation ID | Current declaration |
| --- | --- |
| `ILabel.setText` | `void setText(string text);` |
| `ILabel.text` | `string text();` |
| `ILabel.setFont` | `void setFont(double size, bool bold = false);` |
| `ILabel.setSecondary` | `void setSecondary(bool secondary);` |
| `ILabel.setCentered` | `void setCentered(bool centered);` |
| `ILabel.setWrapping` | `void setWrapping(bool wrapping);` |

## ILevelIndicator

Source: [ILevelIndicator.btrc](../../src/stdlib/GUI/ILevelIndicator.btrc). Extends `IView`. Families: N21/N42.
Milestones: UI4/UI8. Starting cases: E11, E20, E28.

| Operation ID | Current declaration |
| --- | --- |
| `ILevelIndicator.setValue` | `void setValue(double value);` |
| `ILevelIndicator.value` | `double value();` |

## IPanel

Source: [IPanel.btrc](../../src/stdlib/GUI/IPanel.btrc). Extends `IContainer`. Families: N24/N45/N46.
Milestones: UI5. Starting cases: E20, E26, E29, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IPanel.setFill` | `void setFill(RGBA fill);` |
| `IPanel.setCornerRadius` | `void setCornerRadius(double radius);` |
| `IPanel.setDarkAppearance` | `void setDarkAppearance(bool dark);` |
| `IPanel.inheritAppearance` | `void inheritAppearance();` |

## IProgressIndicator

Source: [IProgressIndicator.btrc](../../src/stdlib/GUI/IProgressIndicator.btrc). Extends `IView`. Families: N21/N42/N48.
Milestones: UI4/UI8/UI9. Starting cases: E20, E28, E30, E42.

| Operation ID | Current declaration |
| --- | --- |
| `IProgressIndicator.isRunning` | `bool isRunning();` |
| `IProgressIndicator.setRunning` | `void setRunning(bool running);` |

## IScrollView

Source: [IScrollView.btrc](../../src/stdlib/GUI/IScrollView.btrc). Extends `IContainer`. Families: N26.
Milestones: UI6. Starting cases: E09, E13, E21, E27, E41.

| Operation ID | Current declaration |
| --- | --- |
| `IScrollView.setContentSize` | `void setContentSize(double width, double height);` |
| `IScrollView.scrollOffset` | `double scrollOffset();` |
| `IScrollView.scrollTo` | `void scrollTo(double offset);` |

## ISelect

Source: [ISelect.btrc](../../src/stdlib/GUI/ISelect.btrc). Extends `IView`. Families: N05/N19.
Milestones: UI2/UI4. Starting cases: E02, E13, E15, E23, E33, E39.

| Operation ID | Current declaration |
| --- | --- |
| `ISelect.setItems` | `void setItems(Vector<string> titles, int selectedIndex);` |
| `ISelect.itemCount` | `int itemCount();` |
| `ISelect.selectedIndex` | `int selectedIndex();` |
| `ISelect.setItemEnabled` | `void setItemEnabled(int index, bool enabled);` |
| `ISelect.isItemEnabled` | `bool isItemEnabled(int index);` |
| `ISelect.setSelectedIndex` | `void setSelectedIndex(int index);` |
| `ISelect.selectedTitle` | `string selectedTitle();` |
| `ISelect.setEnabled` | `void setEnabled(bool enabled);` |
| `ISelect.setFont` | `void setFont(double size);` |
| `ISelect.isEnabled` | `bool isEnabled();` |

## ISlider

Source: [ISlider.btrc](../../src/stdlib/GUI/ISlider.btrc). Extends `IView`. Families: N05/N18.
Milestones: UI2/UI4. Starting cases: E03, E13, E28, E34, E39.

| Operation ID | Current declaration |
| --- | --- |
| `ISlider.value` | `double value();` |
| `ISlider.setValue` | `void setValue(double value);` |
| `ISlider.setEnabled` | `void setEnabled(bool enabled);` |
| `ISlider.isEnabled` | `bool isEnabled();` |
| `ISlider.setToolTip` | `void setToolTip(string text);` |
| `ISlider.toolTip` | `string toolTip();` |

## IStack

Source: [IStack.btrc](../../src/stdlib/GUI/IStack.btrc). Extends `IContainer`. Families: N23/N24.
Milestones: UI5. Starting cases: E15, E26, E29, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IStack.spacing` | `double spacing();` |
| `IStack.setSpacing` | `void setSpacing(double spacing);` |
| `IStack.alignment` | `StackAlignment alignment();` |
| `IStack.setAlignment` | `void setAlignment(StackAlignment alignment);` |
| `IStack.setPadding` | `void setPadding(double top, double right, double bottom, double left);` |
| `IStack.layout` | `void layout();` |

## ITextField

Source: [ITextField.btrc](../../src/stdlib/GUI/ITextField.btrc). Extends `IView`. Families: N05/N10/N15.
Milestones: UI2/UI3/UI4. Starting cases: E01, E07, E14, E19, E39, E44, E45.

| Operation ID | Current declaration |
| --- | --- |
| `ITextField.text` | `string text();` |
| `ITextField.setText` | `void setText(string text);` |
| `ITextField.setPlaceholder` | `void setPlaceholder(string text);` |
| `ITextField.isEnabled` | `bool isEnabled();` |
| `ITextField.setEnabled` | `void setEnabled(bool enabled);` |
| `ITextField.setFont` | `void setFont(double size);` |

## IViewPointerHandler

Source: [IView.btrc](../../src/stdlib/GUI/IView.btrc). Families: N08.
Milestones: UI3. Starting cases: E03, E27, E39, E40.

| Operation ID | Current declaration |
| --- | --- |
| `IViewPointerHandler.pointer` | `bool pointer(AppPointerEvent event);` |

## IViewScrollHandler

Source: [IView.btrc](../../src/stdlib/GUI/IView.btrc). Families: N08/N26.
Milestones: UI3/UI6. Starting cases: E27, E40, E41.

| Operation ID | Current declaration |
| --- | --- |
| `IViewScrollHandler.scroll` | `bool scroll(AppScrollEvent event);` |

## IView

Source: [IView.btrc](../../src/stdlib/GUI/IView.btrc). Families: N03/N06/N08/N23/N24.
Milestones: UI2/UI3/UI5. Starting cases: E05, E26, E27, E29, E31, E39.

| Operation ID | Current declaration |
| --- | --- |
| `IView.isOpen` | `bool isOpen();` |
| `IView.fittingWidth` | `double fittingWidth();` |
| `IView.fittingHeight` | `double fittingHeight();` |
| `IView.arrange` | `void arrange(double x, double y, double width, double height);` |
| `IView.isVisible` | `bool isVisible();` |
| `IView.setVisible` | `void setVisible(bool visible);` |
| `IView.onPointer` | `ICallbackRegistration onPointer(IViewPointerHandler handler, CallbackScope owner);` |
| `IView.onScroll` | `ICallbackRegistration onScroll(IViewScrollHandler handler, CallbackScope owner);` |
| `IView.close` | `CallbackCancellation close();` |
| `IView.pollClose` | `CallbackCancellation pollClose();` |

## IWindowKeyHandler

Source: [IWindow.btrc](../../src/stdlib/GUI/IWindow.btrc). Families: N07/N10.
Milestones: UI3. Starting cases: E06, E13, E25, E40.

| Operation ID | Current declaration |
| --- | --- |
| `IWindowKeyHandler.key` | `bool key(AppKeyboardEvent event);` |

## IWindow

Source: [IWindow.btrc](../../src/stdlib/GUI/IWindow.btrc). Families: N02/N07/N25/N35.
Milestones: UI1/UI3/UI5/UI7. Starting cases: E05, E08, E16, E23, E27, E42, E46, E47.

| Operation ID | Current declaration |
| --- | --- |
| `IWindow.isOpen` | `bool isOpen();` |
| `IWindow.title` | `string title();` |
| `IWindow.setTitle` | `void setTitle(string title);` |
| `IWindow.contentWidth` | `double contentWidth();` |
| `IWindow.contentHeight` | `double contentHeight();` |
| `IWindow.setContentSize` | `void setContentSize(double width, double height);` |
| `IWindow.setMinimumContentSize` | `void setMinimumContentSize(double width, double height);` |
| `IWindow.root` | `IView? root();` |
| `IWindow.attachRoot` | `void attachRoot(IView view);` |
| `IWindow.detachRoot` | `IView? detachRoot();` |
| `IWindow.show` | `void show();` |
| `IWindow.hide` | `void hide();` |
| `IWindow.isVisible` | `bool isVisible();` |
| `IWindow.isFocused` | `bool isFocused();` |
| `IWindow.showAlert` | `void showAlert(string title, string message);` |
| `IWindow.onKey` | `ICallbackRegistration onKey(IWindowKeyHandler handler, CallbackScope owner);` |
| `IWindow.close` | `CallbackCancellation close();` |
| `IWindow.pollClose` | `CallbackCancellation pollClose();` |

## GUI factories and services

Source: [GUI.btrc](../../src/stdlib/GUI/GUI.btrc). UI1 qualifies provider selection
and creation; UI2 qualifies application work and lifetime; UI4–UI7 qualify the
returned controls/services; UI9/UI10 qualify text rasterization and capture.
Link each factory to its returned owner's assertions above. Text rasterization
also needs E37; capture needs E38; application lifecycle/work needs E04, E30,
E31 and E40. These facade methods do not replace receiver-level coverage.

| Operation ID | Current class-method declaration |
| --- | --- |
| `GUI.initialize` | `class void initialize(int workCapacity = 256)` |
| `GUI.createWindow` | `class IWindow createWindow(string title, double width, double height)` |
| `GUI.createButton` | `class IButton createButton(string title)` |
| `GUI.createTextField` | `class ITextField createTextField(string text = "", string placeholder = "")` |
| `GUI.createContainer` | `class IContainer createContainer()` |
| `GUI.createRow` | `class IStack createRow(double spacing = 8.0)` |
| `GUI.createColumn` | `class IStack createColumn(double spacing = 8.0)` |
| `GUI.createGPUView` | `class IGPUView createGPUView(bool capture = false)` |
| `GUI.createLabel` | `class ILabel createLabel(string text = "")` |
| `GUI.createImageView` | `class IImageView createImageView()` |
| `GUI.createImageHandle` | `class IImageHandle createImageHandle(Image pixels, int maximumPixels = 16777216)` |
| `GUI.createPanel` | `class IPanel createPanel(RGBA fill, double radius = 0.0)` |
| `GUI.createProgressIndicator` | `class IProgressIndicator createProgressIndicator()` |
| `GUI.createLevelIndicator` | `class ILevelIndicator createLevelIndicator(double warning, double critical)` |
| `GUI.createSlider` | `class ISlider createSlider(double minimum, double maximum, int intervals = 0)` |
| `GUI.createSelect` | `class ISelect createSelect()` |
| `GUI.createScrollView` | `class IScrollView createScrollView()` |
| `GUI.createGrid` | `class IGrid createGrid(int columns, int rows, double columnSpacing = 0.0, double rowSpacing = 0.0)` |
| `GUI.chooseDirectory` | `class DirectoryPickerOutcome chooseDirectory(DirectoryPickerRequest request)` |
| `GUI.rasterizeText` | `class void rasterizeText(TextRasterization request)` |
| `GUI.rasterText` | `class Image rasterText(TextRun run)` |
| `GUI.capture` | `class Image capture(IView root, Vector<GUICaptureLayer> layers)` |
| `GUI.post` | `class void post(IApplicationWork work)` |
| `GUI.postAfter` | `class ICallbackRegistration postAfter(double delaySeconds, IApplicationWork work)` |
| `GUI.requestQuit` | `class void requestQuit()` |
| `GUI.run` | `class void run()` |
| `GUI.close` | `class CallbackCancellation close()` |

## Missing contracts to add before widening the widget set

Existing declarations alone cannot express the following product behavior.
These are recommended additions to the existing owners, not frozen API names
or permission to create a parallel GUI runtime. The 60-family roadmap retains
the full missing-control list and extended toolkit scope.

| First contract increment | Existing owner to extend | Completion evidence |
| --- | --- | --- |
| Edit, selection and range subscriptions | `ITextField`, `ISelect`, `ISlider`; reuse scoped callback ownership | E01–E03/E33/E34: one accepted commit, zero setter-generated actions; active composition and stable-key selection survive refresh. |
| Focus and semantic command routing | `IView`, `IWindow`, App event values | E05/E06/E13/E25: native/GPU traversal, editor shortcut precedence, platform modifiers and no focus traps. |
| Worker completion and fair dispatch | `IApplication` and provider loop owners | E04/E24/E40: idle-loop wakeup, bounded capacity, lossless terminal events, cancellation and progress under load. |
| Scene and dismissal transactions | Application/window owners plus product document state | E08/E16/E17/E46/E47: independent scenes, cold/warm activation, async Save/Discard/Cancel and durable restoration. |
| Constrained layout and viewport observation | `IView`, containers, `IWindow` | E15/E18/E26/E27/E39: wrapping, baselines, safe areas, keyboard occlusion, RTL and effective interaction state. |
| Native collections and stable selection | New cohesive collection/data-source owners using existing view/container lifetimes | E09/E21/E29: virtual list/table/tree contracts, keyed updates, bounded realization and accessible offscreen items. `IGrid` is a fixed-cell layout container. |
| Async presentation and resource selection | Window presentation and picker owners | E10/E22/E23: parent-owned completion, cancellation, scoped resources and usable non-path selections. |
| OS accessibility attachment and operations | Shared semantic values with native view/provider bridges | E11/E21/E28: names, relations, stable identity, native action/text/range operations and accessible GPU children. |
| Display pacing and recoverable resources | `IGPUView`, window exposure and scheduler owners | E12/E32/E38/E42/E43: measured presentation, coherent capture, zero settled hidden redraw and recovery without losing native edits. |

Recommended first review packet: the event payload and lifetime contracts for
text/select/range, editor/focus fixture results, and each platform's native-shell
feasibility result. Keep the remaining operations visible as open work; do not
turn completion of that first slice into a five-platform parity claim.
