import { useState, useEffect } from "react";
import Downshift from "downshift";
import { useWatch } from "react-hook-form";
import { Button } from "@canonical/react-components";

import type {
  UseFormRegister,
  UseFormSetValue,
  UseFormGetValues,
  Control,
  FieldValues,
} from "react-hook-form";

type DataItem = {
  key: string;
  name: string;
};

type Props = {
  data: DataItem[];
  field: string;
  currentValues: string[];
  register: UseFormRegister<FieldValues>;
  setValue: UseFormSetValue<FieldValues>;
  getValues: UseFormGetValues<FieldValues>;
  control: Control<FieldValues>;
  disabled?: boolean;
};

function SearchAutocomplete({
  data,
  field,
  currentValues,
  register,
  setValue,
  getValues,
  control,
  disabled,
}: Props): React.JSX.Element {
  const [selections, setSelections] = useState(() => {
    return data.filter((value) => currentValues.includes(value.key));
  });

  const getNewSelectionKeys = (newSelections: DataItem[]): string => {
    return newSelections
      .map((selection: DataItem) => selection.key)
      .sort()
      .join(" ");
  };

  const shouldDirty = (newSelectionsKeys: string) => {
    return newSelectionsKeys !== getValues(field);
  };

  const selectionKeyValues = useWatch({
    control,
    name: field,
  });

  useEffect(() => {
    setSelections(() => {
      return data.filter((value) => selectionKeyValues.includes(value.key));
    });
  }, [selectionKeyValues]);

  return (
    <Downshift
      onChange={(selection) => {
        const newSelections = selections.concat([selection]);
        const newSelectionsKeys = getNewSelectionKeys(newSelections);

        setSelections(newSelections);
        setValue(field, newSelectionsKeys, {
          shouldDirty: shouldDirty(newSelectionsKeys),
        });
      }}
      itemToString={() => ""}
    >
      {({
        getInputProps,
        getItemProps,
        getMenuProps,
        isOpen,
        inputValue,
        highlightedIndex,
      }) => (
        <div className="p-multiselect">
          {selections.map((suggestion: DataItem) => (
            <span key={suggestion.key} className="p-multiselect__item">
              {suggestion.name}
              <Button
                type="button"
                style={{
                  backgroundColor: "transparent",
                  border: 0,
                  color: "inherit",
                  margin: 0,
                  padding: 0,
                }}
                onClick={() => {
                  const newSelections = selections.filter(
                    (item: DataItem) => item.key !== suggestion.key,
                  );

                  const newSelectionsKeys = getNewSelectionKeys(newSelections);

                  setSelections(newSelections);
                  setValue(field, newSelectionsKeys, {
                    shouldDirty: shouldDirty(newSelectionsKeys),
                  });
                }}
              >
                <i className="p-icon--close p-multiselect__item-remove">
                  Remove suggestion
                </i>
              </Button>
            </span>
          ))}

          <input type="hidden" {...register(field)} />

          <input
            type="text"
            className="p-multiselect__input"
            disabled={disabled}
            {...getInputProps()}
          />

          {isOpen && (
            <ul className="p-multiselect__options" {...getMenuProps()}>
              {data
                .filter(
                  (item) =>
                    !inputValue ||
                    item.key.toLowerCase().includes(inputValue) ||
                    item.name.toLowerCase().includes(inputValue),
                )
                .map((item, index) => (
                  <li
                    key={item.key}
                    className="p-multiselect__option"
                    {...getItemProps({
                      index,
                      item,
                      style: {
                        backgroundColor:
                          highlightedIndex === index ? "#f7f7f7" : "#fff",
                      },
                    })}
                  >
                    {item.name}
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}
    </Downshift>
  );
}

export default SearchAutocomplete;
